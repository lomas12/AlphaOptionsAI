"""Universal market scanner universe: dynamically builds and maintains the
set of optionable US symbols, replacing any hardcoded watchlist.

Sources (both official, both free, no API key, downloaded — never invented):
- NASDAQ Trader symbol directories: every security listed on US exchanges
  (nasdaqlisted.txt + otherlisted.txt, updated nightly by NASDAQ).
- CBOE equity/index options directory: every symbol with options listed on
  CBOE exchanges — the authoritative "has listed options" filter.

Universe = (US-listed, non-test securities) INTERSECT (CBOE optionable).
Symbols with no listed options never enter the universe, so the scanner
never wastes calls on them.

Honesty rules (matching the rest of the bot):
- If the sources are unreachable, the previously cached universe stays in
  service; it is never padded or guessed.
- If there is no cache at all, the universe is reported as empty/unavailable
  — downstream callers say so instead of scanning a fabricated list.
- Prescreen metrics come from real downloaded bars only; symbols whose data
  is missing or NaN are skipped, never filled in.
"""

import asyncio
import csv
import io
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

from core import database

logger = logging.getLogger("alphaoptionsai.universe")

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
CBOE_DIRECTORY_URL = "https://www.cboe.com/us/options/symboldir/equity_index_options/?download=csv"

HTTP_TIMEOUT_SECONDS = 30
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AlphaOptionsAI/1.0"

REFRESH_MAX_AGE_HOURS = 24          # get_optionable_symbols cache lifetime
MIN_SANE_UNIVERSE = 500             # fewer symbols than this = parser/source drift, keep old cache
AUDIT_SAMPLE_SIZE = 8               # random live options-chain checks per refresh

# Plain 1-5 letter symbols only. Class/preferred share forms (BRK.B, PBR.A)
# are deliberately excluded: NASDAQ, CBOE, and Yahoo each spell them
# differently (BRK.B / BRK B / BRK-B) and they are a tiny sliver of options
# flow — a documented tradeoff, not an accident.
SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")

# Prescreen floors: symbols must be liquid enough for a tradable options
# market. These filter real data; they do not synthesize any.
PRESCREEN_MIN_PRICE = 5.0
PRESCREEN_MAX_PRICE = 2500.0
PRESCREEN_MIN_DOLLAR_VOLUME = 20_000_000  # avg daily $ volume
PRESCREEN_BATCH_SIZE = 100
PRESCREEN_MAX_CONCURRENT_BATCHES = 2
PRESCREEN_BATCH_STAGGER_SECONDS = 1.5

OTHER_LISTED_EXCHANGES = {
    "N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX",
}


@dataclass
class RefreshResult:
    refreshed: bool
    reason: str
    total_active: int
    added: int = 0
    deactivated: int = 0
    sources: str = ""


@dataclass
class ValidationResult:
    ok: bool
    symbol: str
    reason: str


@dataclass
class Candidate:
    """One prescreen survivor, ranked by activity. Every field is computed
    from real downloaded bars."""
    symbol: str
    price: float
    change_pct: float
    volume_ratio: float
    dollar_volume: float
    score: float


class UniverseUnavailableError(Exception):
    """No cached universe exists and the official sources are unreachable."""


def _download(url: str) -> str:
    resp = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.text


def _parse_nasdaq_listed(text: str) -> dict[str, tuple[str, str, bool]]:
    """nasdaqlisted.txt -> {symbol: (name, exchange, is_etf)}. Pipe-delimited,
    header row first, 'File Creation Time' footer last, Test Issue flag col."""
    out: dict[str, tuple[str, str, bool]] = {}
    for line in text.splitlines()[1:]:
        if not line or line.startswith("File Creation Time"):
            continue
        parts = line.split("|")
        if len(parts) < 7:
            continue
        symbol, name, _category, test_issue, _status, _lot, etf = (p.strip() for p in parts[:7])
        if test_issue != "N" or not SYMBOL_RE.match(symbol):
            continue
        out[symbol] = (name, "NASDAQ", etf == "Y")
    return out


def _parse_other_listed(text: str) -> dict[str, tuple[str, str, bool]]:
    """otherlisted.txt (NYSE/AMEX/ARCA/BATS/IEX) -> {symbol: (name, exchange, is_etf)}."""
    out: dict[str, tuple[str, str, bool]] = {}
    for line in text.splitlines()[1:]:
        if not line or line.startswith("File Creation Time"):
            continue
        parts = line.split("|")
        if len(parts) < 7:
            continue
        symbol = parts[0].strip()
        name = parts[1].strip()
        exchange = OTHER_LISTED_EXCHANGES.get(parts[2].strip(), parts[2].strip())
        etf = parts[4].strip() == "Y"
        test_issue = parts[6].strip()
        if test_issue != "N" or not SYMBOL_RE.match(symbol):
            continue
        out[symbol] = (name, exchange, etf)
    return out


def _parse_cboe_symbols(text: str) -> set[str]:
    """CBOE options directory CSV -> set of optionable symbols. Locates the
    'Stock Symbol' column by header name so column reordering can't silently
    poison the universe."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return set()
    symbol_idx = None
    for i, col in enumerate(header):
        if "stock symbol" in col.strip().lower():
            symbol_idx = i
            break
    if symbol_idx is None:
        logger.error("CBOE directory format changed: no 'Stock Symbol' column in header %r", header)
        return set()
    symbols: set[str] = set()
    for row in reader:
        if len(row) <= symbol_idx:
            continue
        sym = row[symbol_idx].strip().upper()
        if SYMBOL_RE.match(sym):
            symbols.add(sym)
    return symbols


def _last_refresh_age_hours() -> Optional[float]:
    raw = database.get_setting("universe_last_refresh_utc")
    if not raw:
        return None
    try:
        then = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600


async def _audit_sample(symbols: list[str]) -> bool:
    """Deep-check a small random sample against live options chains. Returns
    False only if EVERY sampled symbol fails — the signal that the freshly
    parsed universe (or the data provider) is broken and the old cache should
    stay in service."""
    from apis import router  # local import: keeps this module importable without provider deps at test time

    sample = random.sample(symbols, min(AUDIT_SAMPLE_SIZE, len(symbols)))
    if not sample:
        return True
    successes = 0
    for sym in sample:
        result = await asyncio.to_thread(router.get_option_expirations, sym)
        if result.available and result.value:
            successes += 1
    logger.info("Universe audit: %d/%d sampled symbols have live options chains", successes, len(sample))
    return successes > 0


async def refresh_symbol_database(force: bool = False) -> RefreshResult:
    """Rebuild the optionable-symbol universe from the official sources.

    Skips work if the cache is younger than REFRESH_MAX_AGE_HOURS (unless
    forced). On any source failure or sanity-check failure the existing
    cached universe is left untouched.
    """
    age = _last_refresh_age_hours()
    cached = database.get_universe_stats().active
    if not force and age is not None and age < REFRESH_MAX_AGE_HOURS and cached > 0:
        return RefreshResult(refreshed=False, reason=f"cache is {age:.1f}h old (< {REFRESH_MAX_AGE_HOURS}h)", total_active=cached)

    downloads = await asyncio.gather(
        asyncio.to_thread(_download, NASDAQ_LISTED_URL),
        asyncio.to_thread(_download, OTHER_LISTED_URL),
        asyncio.to_thread(_download, CBOE_DIRECTORY_URL),
        return_exceptions=True,
    )
    nasdaq_raw, other_raw, cboe_raw = downloads

    if isinstance(cboe_raw, BaseException):
        logger.error("CBOE options directory unreachable (%s); keeping cached universe of %d symbols", cboe_raw, cached)
        if cached == 0:
            raise UniverseUnavailableError("Optionable-symbol sources unreachable and no cached universe exists.")
        return RefreshResult(refreshed=False, reason="CBOE directory unreachable", total_active=cached)

    optionable = _parse_cboe_symbols(cboe_raw)

    listings: dict[str, tuple[str, str, bool]] = {}
    sources = "cboe"
    for raw, parser, label in ((nasdaq_raw, _parse_nasdaq_listed, "nasdaq"), (other_raw, _parse_other_listed, "nyse/other")):
        if isinstance(raw, BaseException):
            logger.warning("Listing source %s unreachable: %s", label, raw)
            continue
        listings.update(parser(raw))
        sources += f"+{label}"

    if listings:
        # Primary path: exchange listing ∩ CBOE optionable.
        rows = [
            (sym, listings[sym][0], listings[sym][1], listings[sym][2], sources)
            for sym in optionable if sym in listings
        ]
    else:
        # Both listing files failed but CBOE worked: CBOE alone is still a
        # real, official optionable list — use it without names/exchanges.
        rows = [(sym, None, None, False, "cboe_only") for sym in sorted(optionable)]

    if len(rows) < MIN_SANE_UNIVERSE:
        logger.error(
            "Parsed universe suspiciously small (%d < %d) — source format may have changed; keeping cached universe",
            len(rows), MIN_SANE_UNIVERSE,
        )
        if cached == 0:
            raise UniverseUnavailableError(f"Universe build produced only {len(rows)} symbols and no cache exists.")
        return RefreshResult(refreshed=False, reason=f"sanity check failed ({len(rows)} symbols)", total_active=cached)

    if not await _audit_sample([r[0] for r in rows]):
        logger.error("Universe audit failed for every sampled symbol; keeping cached universe")
        if cached > 0:
            return RefreshResult(refreshed=False, reason="live options audit failed", total_active=cached)
        # No cache to fall back to: store anyway (sources are official) but say so.
        logger.warning("No cached universe exists — storing unaudited universe from official sources")

    added, deactivated, total_active = database.replace_universe(rows)
    database.set_setting("universe_last_refresh_utc", datetime.now(timezone.utc).isoformat())
    database.set_setting("universe_sources", sources)
    logger.info(
        "Universe refreshed from %s: %d optionable symbols (%d added, %d deactivated)",
        sources, total_active, added, deactivated,
    )
    return RefreshResult(refreshed=True, reason="refreshed", total_active=total_active, added=added, deactivated=deactivated, sources=sources)


def get_optionable_symbols(limit: Optional[int] = None) -> list[str]:
    """Current cached optionable universe (alphabetical). Empty list means
    the universe hasn't been built yet — callers must treat that as
    'unavailable', never substitute a made-up list."""
    symbols = database.get_universe_symbols(active_only=True)
    return symbols[:limit] if limit else symbols


async def ensure_fresh(max_age_hours: float = 26.0) -> Optional[RefreshResult]:
    """Refresh on startup if the cache is empty or stale. Never raises on
    source failure when a cache exists — the bot keeps running on the cache."""
    age = _last_refresh_age_hours()
    if get_optionable_symbols(limit=1) and age is not None and age < max_age_hours:
        return None
    try:
        return await refresh_symbol_database(force=True)
    except UniverseUnavailableError:
        raise
    except Exception as exc:
        logger.error("Startup universe refresh failed: %s", exc)
        return None


async def validate_symbol(raw: str, deep: bool = False) -> ValidationResult:
    """Validate a symbol before any scan.

    Fast path: format check + cached-universe membership. With deep=True an
    unknown symbol gets one live options-chain lookup — so a brand-new
    listing still validates, and if it passes it is added to the universe.
    Never guesses: an unverifiable symbol is rejected, not assumed.
    """
    from apis.yahoo import clean_ticker

    symbol = clean_ticker(raw or "")
    if not symbol or not SYMBOL_RE.match(symbol):
        return ValidationResult(ok=False, symbol=symbol or (raw or "").upper(), reason=f"'{raw}' is not a valid US stock symbol.")

    if database.is_in_universe(symbol):
        return ValidationResult(ok=True, symbol=symbol, reason="in optionable universe")

    if not deep:
        return ValidationResult(ok=False, symbol=symbol, reason=f"{symbol} is not in the optionable-US-stock universe.")

    from apis import router

    expirations = await asyncio.to_thread(router.get_option_expirations, symbol)
    if expirations.available and expirations.value:
        database.add_universe_symbol(symbol, None, None, False, source="live_validation")
        logger.info("Validated %s via live options chain; added to universe", symbol)
        return ValidationResult(ok=True, symbol=symbol, reason="verified live options chain")

    quote = await asyncio.to_thread(router.get_quote, symbol)
    if quote.available:
        return ValidationResult(ok=False, symbol=symbol, reason=f"{symbol} trades, but has no listed options — nothing to scan.")
    return ValidationResult(ok=False, symbol=symbol, reason=f"Could not verify {symbol} against live market data. It may be delisted or not a US-listed symbol.")


def _prescreen_batch_sync(symbols: list[str]) -> list[Candidate]:
    """Download recent daily bars for one batch and compute activity metrics.
    Symbols with missing/NaN data are skipped — never estimated."""
    import pandas as pd
    import yfinance as yf

    try:
        df = yf.download(
            symbols, period="5d", interval="1d", group_by="ticker",
            threads=True, progress=False, auto_adjust=True,
        )
    except Exception as exc:
        logger.warning("Prescreen batch download failed (%d symbols): %s", len(symbols), exc)
        return []
    if df is None or df.empty:
        return []

    out: list[Candidate] = []
    for sym in symbols:
        try:
            sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
            closes = sub["Close"].dropna()
            volumes = sub["Volume"].dropna()
            if len(closes) < 2 or volumes.empty:
                continue
            price = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            last_vol = float(volumes.iloc[-1])
            avg_vol = float(volumes.mean())
            if prev <= 0 or avg_vol <= 0 or price <= 0:
                continue
            if not (PRESCREEN_MIN_PRICE <= price <= PRESCREEN_MAX_PRICE):
                continue
            dollar_volume = avg_vol * price
            if dollar_volume < PRESCREEN_MIN_DOLLAR_VOLUME:
                continue
            change_pct = (price - prev) / prev * 100
            volume_ratio = last_vol / avg_vol
            # Transparent ranking heuristic over the real metrics above —
            # the metrics themselves are what get displayed, the score only
            # orders them: movement + volume surge + liquidity depth.
            score = abs(change_pct) * 2.0 + max(volume_ratio - 1.0, 0.0) * 3.0 + min(dollar_volume / 1e8, 3.0)
            out.append(Candidate(
                symbol=sym, price=round(price, 2), change_pct=round(change_pct, 2),
                volume_ratio=round(volume_ratio, 2), dollar_volume=round(dollar_volume, 0),
                score=round(score, 3),
            ))
        except Exception:
            continue  # symbol missing from response = no data, skip honestly
    return out


async def prescreen(symbols: list[str], batch_size: int = PRESCREEN_BATCH_SIZE) -> list[Candidate]:
    """Batched, concurrency-limited prescreen of many symbols. Returns
    candidates ranked by activity score (best first)."""
    if not symbols:
        return []
    batches = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]
    semaphore = asyncio.Semaphore(PRESCREEN_MAX_CONCURRENT_BATCHES)

    async def run_batch(index: int, batch: list[str]) -> list[Candidate]:
        async with semaphore:
            if index:
                await asyncio.sleep(PRESCREEN_BATCH_STAGGER_SECONDS)
            return await asyncio.to_thread(_prescreen_batch_sync, batch)

    results = await asyncio.gather(*(run_batch(i, b) for i, b in enumerate(batches)))
    candidates = [c for batch in results for c in batch]
    candidates.sort(key=lambda c: c.score, reverse=True)
    logger.info("Prescreened %d symbols in %d batches -> %d candidates", len(symbols), len(batches), len(candidates))
    return candidates
