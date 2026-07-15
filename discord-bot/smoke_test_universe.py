"""One-shot smoke test for the universal market scanner (no Discord needed)."""
import asyncio
import logging
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

from core import database, universe


async def main() -> None:
    t0 = time.time()
    print("=== 1. refresh_symbol_database(force=True) ===")
    result = await universe.refresh_symbol_database(force=True)
    print(f"refreshed={result.refreshed} reason={result.reason!r} active={result.total_active} "
          f"added={result.added} deactivated={result.deactivated} sources={result.sources!r} ({time.time()-t0:.1f}s)")
    assert result.total_active > 500, "universe too small"

    print("\n=== 2. get_optionable_symbols ===")
    syms = universe.get_optionable_symbols()
    print(f"count={len(syms)} first10={syms[:10]} last5={syms[-5:]}")
    stats = database.get_universe_stats()
    print(f"stats: active={stats.active} inactive={stats.inactive} etfs={stats.etfs} last_refresh={stats.last_refresh_utc}")
    for expected in ("AAPL", "NVDA", "SPY", "TSLA"):
        assert expected in syms, f"{expected} missing from universe!"
    print("AAPL/NVDA/SPY/TSLA all present ✓")

    print("\n=== 3. validate_symbol ===")
    fast = await universe.validate_symbol("AAPL")
    print(f"AAPL (fast): ok={fast.ok} reason={fast.reason!r}")
    assert fast.ok
    junk = await universe.validate_symbol("NOTAREALTICKER")
    print(f"NOTAREALTICKER: ok={junk.ok} reason={junk.reason!r}")
    assert not junk.ok
    fake = await universe.validate_symbol("ZZZQ", deep=True)
    print(f"ZZZQ (deep): ok={fake.ok} reason={fake.reason!r}")
    assert not fake.ok
    lower = await universe.validate_symbol("  msft ")
    print(f"' msft ' (fast): ok={lower.ok} symbol={lower.symbol} reason={lower.reason!r}")
    assert lower.ok and lower.symbol == "MSFT"

    print("\n=== 4. prescreen (150-symbol slice, batched async) ===")
    t1 = time.time()
    # Use a slice guaranteed to include liquid names for a meaningful result.
    test_slice = sorted(set(syms[:130] + ["AAPL", "NVDA", "TSLA", "SPY", "AMD", "META", "MSFT", "AMZN", "QQQ", "PLTR"]))
    candidates = await universe.prescreen(test_slice)
    print(f"prescreened {len(test_slice)} symbols -> {len(candidates)} candidates in {time.time()-t1:.1f}s")
    for c in candidates[:8]:
        print(f"  {c.symbol:<6} ${c.price:>8,.2f}  {c.change_pct:+6.2f}%  vol {c.volume_ratio:4.1f}x  ${c.dollar_volume/1e6:,.0f}M/day  score={c.score}")
    assert candidates, "prescreen returned nothing for a slice containing megacaps"
    assert any(c.symbol in {"AAPL", "NVDA", "MSFT", "SPY"} for c in candidates), "megacaps missing from candidates"

    print("\n=== 5. second refresh respects cache ===")
    cached = await universe.refresh_symbol_database(force=False)
    print(f"refreshed={cached.refreshed} reason={cached.reason!r}")
    assert not cached.refreshed

    print(f"\nALL SMOKE TESTS PASSED ({time.time()-t0:.1f}s total)")


if __name__ == "__main__":
    asyncio.run(main())
