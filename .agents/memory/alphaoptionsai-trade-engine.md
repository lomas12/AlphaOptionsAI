---
name: AlphaOptionsAI trade engine design
description: Architecture decisions for the AlphaOptionsAI Discord options-scanner bot's V2 single-trade decision engine, self-learning confidence, and data fallbacks.
---

The bot (in `discord-bot/`) picks exactly one trade (BUY CALL / BUY PUT / NO TRADE) per `/scan`, never both a call and a put. Confidence blends two halves 50/50: a liquidity/greeks score (OI, volume, vol/OI, IV, spread, distance from spot, DTE) and a "conviction" score built from tagged technical + context signals (EMA20/50/200 stack, RSI, MACD, volume, support/resistance, SPY/QQQ trend, VIX, news sentiment, analyst actions, earnings proximity).

**Why tags, not a fixed formula:** each active signal is a named tag (e.g. `macd_bullish`, `resistance_overhead`) with a learned weight stored in SQLite (`strategy_weights` table). Every 15 minutes an open recommendation that hits TP/SL/expiration gets closed out, and `database.apply_learning()` nudges the weights of whichever tags were active in that trade (±5%, bounded 0.5–2.0). This is how "increase confidence for strategies that work" is implemented — future scores for the same tag combination shift based on real outcomes, not a static rulebook.

**Action threshold:** confidence must be ≥70% to output an actual BUY CALL/PUT; below that the top-level recommendation becomes NO TRADE regardless of directional lean. The morning auto-scan into `#trade-alerts` uses a stricter ≥80% bar.

**Data fallbacks, never fabricate:** every technical/context factor (RSI, MACD, earnings date, news sentiment, analyst rating) comes from a real yfinance call wrapped in try/except; on failure the factor is `None`/skipped rather than guessed, and that tag simply doesn't contribute to conviction that scan.

**Account balance / position sizing:** no persistent per-user balance exists yet; the engine assumes a default $10,000 account (`ACCOUNT_BALANCE_DEFAULT` in `trade_engine.py`) for the 1–2% risk sizing math. If the user wants per-user balances, that needs a new command/table — not yet built.
