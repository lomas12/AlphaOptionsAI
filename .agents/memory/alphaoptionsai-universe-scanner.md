---
name: AlphaOptionsAI universal market scanner
description: How the bot's optionable-US-stock universe is built and why the scanner uses a rotating funnel instead of scanning everything every cycle.
---

# Universal market scanner (core/universe.py)

**Universe sources:** the optionable universe is the intersection of two official free
directories — NASDAQ Trader symbol files (nasdaqlisted.txt + otherlisted.txt, pipe-delimited,
"File Creation Time" footer, Test Issue flag) and CBOE's equity/index options directory CSV
(locate the "Stock Symbol" column by header name, not position). ~5,300 symbols as of Jul 2026.
**Why:** CBOE membership IS the "has listed options" test — no per-symbol chain probing needed
at refresh time; the exchange-listing intersection drops pure index roots (SPX/VIX) naturally.

**Refresh safety rails:** refresh never wipes the cache on failure — source unreachable,
parsed universe < 500 symbols (format-drift guard), or an 8-symbol live-chain audit failing
completely all keep the previous universe in service. Delisted symbols are marked inactive,
not deleted. No cache + no sources = explicit "universe unavailable", never a made-up list.

**Funnel, not brute force:** a full V4 analysis is dozens of API calls, so scanning 5k symbols
per cycle would be ~100k+ requests. Instead: rotating 400-symbol slice per 10-min cycle →
batched yf.download prescreen (100/batch, 2 concurrent, real bars only, price/dollar-volume
floors) → ranked hot list carried across cycles → top 8 get the full engine, with a 90-min
per-symbol cooldown. Market-hours gated. Full universe coverage ≈ every ~2.2h of trading.

**Symbol format tradeoff:** universe is plain `^[A-Z]{1,5}$` only; class/preferred forms
(BRK.B) are deliberately excluded because NASDAQ/CBOE/Yahoo spell them three different ways.

**/scan validation:** cached-universe membership is the fast path; unknown symbols get ONE
live options-chain lookup (deep=True) so brand-new listings still work and are then added to
the universe (source="live_validation") — self-maintaining between daily refreshes.
