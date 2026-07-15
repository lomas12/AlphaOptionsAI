"""Background jobs for the universal market scanner:

- 10-minute universe sweep (market hours only): prescreens a rotating slice
  of the full optionable-US-stock universe with batched bulk downloads,
  maintains a ranked hot list, and runs the full V4 decision engine on the
  top candidates. No hardcoded watchlist anywhere.
- Daily universe refresh (08:15 UTC, pre-market) from the official NASDAQ +
  CBOE directories.
- 15-minute open-trade monitor (win/loss + self-learning).
- Posting qualifying trades to #trade-alerts.

Registered once from bot.py's on_ready.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timezone
from typing import Optional

import discord
from discord.ext import tasks

from apis import router
from core import ai_engine, database, market_data as market_data_module, scanner as scanner_module, universe

logger = logging.getLogger("alphaoptionsai.alerts")

TRADE_ALERTS_CHANNEL_NAME = "trade-alerts"
SCAN_INTERVAL_MINUTES = 10          # one rotating universe slice per cycle
MONITOR_INTERVAL_MINUTES = 15
PRESCREEN_SLICE_SIZE = 400          # symbols prescreened per cycle (4 batches of 100)
DEEP_SCANS_PER_CYCLE = 8            # full V4 analyses per cycle (each is many API calls)
HOT_LIST_SIZE = 40                  # ranked candidates carried across cycles
HOT_ENTRY_TTL_MINUTES = 150         # candidate expires if not re-confirmed within ~1 rotation
DEEP_SCAN_COOLDOWN_MINUTES = 90     # don't re-analyze the same symbol sooner than this
# 08:15 UTC = pre-market ET, after NASDAQ's nightly symbol-directory update.
# tasks.loop(time=...) fires once daily at that wall-clock time -- an
# hours=24 loop would instead fire immediately on every restart.
UNIVERSE_REFRESH_TIME_UTC = dtime(hour=8, minute=15, tzinfo=timezone.utc)

_background_tasks_started = False

# Scanner state (in-memory; rebuilt naturally within one rotation after a restart).
_rotation_offset = 0
_hot: dict[str, tuple[universe.Candidate, datetime]] = {}
_last_deep_scan: dict[str, datetime] = {}
_last_sweep_at: Optional[datetime] = None


@dataclass
class ScannerState:
    universe_size: int
    market_open: bool
    last_sweep_at: Optional[datetime]
    rotation_offset: int
    hot_candidates: list


def get_scanner_state() -> ScannerState:
    now = datetime.now(timezone.utc)
    _prune_hot(now)
    ranked = sorted((entry[0] for entry in _hot.values()), key=lambda c: c.score, reverse=True)
    return ScannerState(
        universe_size=len(universe.get_optionable_symbols()),
        market_open=market_data_module.is_us_market_hours(now),
        last_sweep_at=_last_sweep_at,
        rotation_offset=_rotation_offset,
        hot_candidates=ranked,
    )


def _prune_hot(now: datetime) -> None:
    expired = [sym for sym, (_c, seen) in _hot.items() if (now - seen).total_seconds() > HOT_ENTRY_TTL_MINUTES * 60]
    for sym in expired:
        del _hot[sym]
    if len(_hot) > HOT_LIST_SIZE:
        ranked = sorted(_hot.items(), key=lambda item: item[1][0].score, reverse=True)
        for sym, _ in ranked[HOT_LIST_SIZE:]:
            del _hot[sym]
    stale_scans = [sym for sym, ts in _last_deep_scan.items() if (now - ts).total_seconds() > 86400]
    for sym in stale_scans:
        del _last_deep_scan[sym]


def _find_trade_alerts_channel(client: discord.Client) -> discord.TextChannel | None:
    for guild in client.guilds:
        for channel in guild.text_channels:
            if channel.name == TRADE_ALERTS_CHANNEL_NAME:
                return channel
    return None


def _is_expired(expiration: str) -> bool:
    try:
        return datetime.strptime(expiration, "%Y-%m-%d").date() < date.today()
    except ValueError:
        return False


def check_open_recommendations_sync() -> None:
    for rec in database.get_open_recommendations():
        chain_result = router.get_option_chain(rec["ticker"], rec["expiration"])
        if not chain_result.available:
            continue
        chain = chain_result.value
        contracts = chain.calls if rec["option_type"] == "CALL" else chain.puts
        match = next((c for c in contracts if abs(c.strike - rec["strike"]) < 0.01), None)
        if match is None:
            continue

        current_premium = (match.bid + match.ask) / 2 if match.bid > 0 and match.ask > 0 else match.last_price
        if current_premium <= 0:
            continue

        entry = rec["entry_premium"]
        return_pct = round((current_premium - entry) / entry * 100, 2)
        expired = _is_expired(rec["expiration"])

        hit_tp = current_premium >= rec["take_profit_1"]
        hit_sl = current_premium <= rec["stop_loss"]

        if not (hit_tp or hit_sl or expired):
            continue

        won = return_pct > 0 if expired else hit_tp
        status = "WIN" if won else "LOSS"

        database.close_recommendation(
            rec["id"], status=status, exit_premium=round(current_premium, 2), return_pct=return_pct,
        )
        try:
            import json
            tags = json.loads(rec["strategy_tags"])
            database.apply_learning(tags, won=won)
        except Exception as exc:
            logger.warning("Failed to apply learning for recommendation %s: %s", rec["id"], exc)

        logger.info("Closed recommendation #%s (%s %s): %s (%.2f%%)", rec["id"], rec["ticker"], rec["option_type"], status, return_pct)


async def _run_scan_and_maybe_alert(client: discord.Client, ticker: str) -> None:
    try:
        decision = await ai_engine.analyze_ticker(ticker)
    except ai_engine.TickerNotFoundError:
        return
    except ai_engine.MarketDataUnavailableError as exc:
        logger.warning("Auto-scan skipped %s: %s", ticker, exc)
        return
    except Exception as exc:
        logger.warning("Auto-scan failed for %s: %s", ticker, exc)
        return

    result = scanner_module.evaluate_for_auto_post(decision)
    if not result.qualifies:
        return

    channel = _find_trade_alerts_channel(client)
    if channel is None:
        logger.warning("No #%s channel found -- skipping alert post for %s.", TRADE_ALERTS_CHANNEL_NAME, ticker)
        return

    from core import bot_embeds  # local import: avoids a circular import at module load time

    contract = decision.contract
    rec_id = database.record_recommendation(
        ticker=decision.ticker, option_type=contract["option_type"], strike=contract["strike"],
        expiration=contract["expiration"], entry_premium=decision.entry,
        take_profit_1=decision.take_profit_1, take_profit_2=decision.take_profit_2,
        stop_loss=decision.stop_loss, confidence=decision.confidence, risk_rating=decision.risk_rating,
        strategy_tags=decision.tags, source="auto_scan",
    )
    embed = bot_embeds.build_trade_decision_embed(decision)
    await channel.send(content="🚨 **High-confidence auto-scan alert**", embed=embed)
    database.record_alert(
        ticker=decision.ticker, recommendation_id=rec_id, confidence=decision.confidence,
        channel=channel.name, message=decision.recommendation,
    )
    logger.info("Posted auto-scan alert for %s (%.1f%% confidence)", decision.ticker, decision.confidence)


async def _sweep_universe_once(client: discord.Client) -> None:
    """One scanner cycle: prescreen the next rotating slice of the universe,
    fold survivors into the hot list, deep-scan the top few."""
    global _rotation_offset, _last_sweep_at

    now = datetime.now(timezone.utc)
    if not market_data_module.is_us_market_hours(now):
        return

    symbols = universe.get_optionable_symbols()
    if not symbols:
        logger.warning("Optionable universe is empty/unavailable -- skipping sweep (no fallback list will be invented).")
        return

    total = len(symbols)
    start = _rotation_offset % total
    slice_ = symbols[start:start + PRESCREEN_SLICE_SIZE]
    if len(slice_) < PRESCREEN_SLICE_SIZE and total > len(slice_):
        slice_ = slice_ + symbols[: PRESCREEN_SLICE_SIZE - len(slice_)]
    _rotation_offset = (start + len(slice_)) % total

    candidates = await universe.prescreen(slice_)
    now = datetime.now(timezone.utc)
    for cand in candidates:
        _hot[cand.symbol] = (cand, now)
    _prune_hot(now)
    _last_sweep_at = now

    targets: list[str] = []
    for cand in sorted((entry[0] for entry in _hot.values()), key=lambda c: c.score, reverse=True):
        last = _last_deep_scan.get(cand.symbol)
        if last and (now - last).total_seconds() < DEEP_SCAN_COOLDOWN_MINUTES * 60:
            continue
        targets.append(cand.symbol)
        if len(targets) >= DEEP_SCANS_PER_CYCLE:
            break

    logger.info(
        "Universe sweep: slice %d-%d of %d, %d prescreen survivors, hot list %d, deep-scanning %s",
        start, start + len(slice_), total, len(candidates), len(_hot), ", ".join(targets) if targets else "none",
    )
    for sym in targets:
        _last_deep_scan[sym] = datetime.now(timezone.utc)
        await _run_scan_and_maybe_alert(client, sym)


async def _startup_universe_init() -> None:
    try:
        result = await universe.ensure_fresh()
        if result is not None:
            logger.info("Startup universe init: %s (%d active symbols)", result.reason, result.total_active)
    except universe.UniverseUnavailableError as exc:
        logger.error("Universe unavailable at startup: %s -- scans will report unavailable until sources are reachable", exc)
    except Exception as exc:
        logger.error("Startup universe init failed: %s", exc)


def register_background_tasks(client: discord.Client) -> None:
    global _background_tasks_started
    if _background_tasks_started:
        return
    _background_tasks_started = True

    client.loop.create_task(_startup_universe_init())

    @tasks.loop(minutes=MONITOR_INTERVAL_MINUTES)
    async def monitor_open_trades() -> None:
        try:
            check_open_recommendations_sync()
        except Exception as exc:
            logger.error("monitor_open_trades failed: %s", exc)

    @tasks.loop(minutes=SCAN_INTERVAL_MINUTES)
    async def universal_scanner() -> None:
        try:
            await _sweep_universe_once(client)
        except Exception as exc:
            logger.error("universal_scanner cycle failed: %s", exc)

    @tasks.loop(time=UNIVERSE_REFRESH_TIME_UTC)
    async def refresh_universe_daily() -> None:
        try:
            result = await universe.refresh_symbol_database(force=True)
            logger.info("Daily universe refresh: %s (%d active symbols)", result.reason, result.total_active)
        except Exception as exc:
            logger.error("Daily universe refresh failed: %s", exc)

    monitor_open_trades.start()
    universal_scanner.start()
    refresh_universe_daily.start()
    logger.info(
        "Background tasks started: monitor_open_trades (every %sm), universal_scanner (every %sm, %d-symbol slices, %d deep scans/cycle), universe refresh daily at %s UTC",
        MONITOR_INTERVAL_MINUTES, SCAN_INTERVAL_MINUTES, PRESCREEN_SLICE_SIZE, DEEP_SCANS_PER_CYCLE, UNIVERSE_REFRESH_TIME_UTC.strftime("%H:%M"),
    )
