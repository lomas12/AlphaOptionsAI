# AlphaOptionsAI V3

A professional AI-powered options trading assistant for Discord. Combines
technical analysis, options-chain analytics, market context, news/sentiment,
and a self-learning confidence engine into a single `/scan` command, plus a
background scanner that watches a ticker list around the clock.

## Architecture

- `apis/` — one module per data provider (`yahoo`, `polygon`, `tradier`,
  `alpaca`, `finnhub`, `benzinga`), all implementing the same function
  signatures defined in `apis/base.py`. `apis/router.py` calls them in
  priority order (Polygon → Tradier → Alpaca → Finnhub → Benzinga → Yahoo)
  and returns the first real result, so the bot never silently fabricates
  data — if nothing is configured beyond Yahoo, non-Yahoo capabilities are
  reported as unavailable rather than guessed.
- `core/` — the actual bot logic: technical indicators, options analytics,
  market context, news/sentiment, earnings, risk/position-sizing, the AI
  decision engine, the backtester, portfolio tracking, the auto-scanner
  gate, the SQLite database layer, and the background job loops.
- `bot.py` — Discord client, slash commands, and wiring.

## Data providers

Only **Yahoo Finance** is enabled out of the box — no API key required. It
supplies live quotes, price history, options chains, news, analyst actions,
earnings calendar, insider transactions, and SEC filings.

The other five providers are fully wired for later upgrades: add the
corresponding environment variable(s) below and the router will
automatically start preferring that provider for the capabilities it
supports — no code changes required.

| Provider | Env vars |
|---|---|
| Polygon.io | `POLYGON_API_KEY` |
| Tradier | `TRADIER_API_KEY` |
| Alpaca | `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` |
| Finnhub | `FINNHUB_API_KEY` |
| Benzinga | `BENZINGA_API_KEY` |

Some capabilities on these providers (e.g. Tradier's options chain, or
Polygon/Finnhub/Alpaca quotes) already have working REST call logic and
activate the moment the key is present. Others are marked with a `# TODO`
in the source and currently return "unavailable" until implemented.

### Known Yahoo-only limitations (clearly labeled wherever they show up)

- **IV Rank / IV Percentile** — Yahoo has no historical IV series, so this
  is a realized-volatility proxy, not true historical IV term structure.
- **Unusual options activity / sweeps** — detected heuristically
  (volume/OI ratio + absolute volume threshold), not from real tape data.
- **Market breadth (advance/decline)** — reported as unavailable; requires
  a premium data feed.
- **Backtester** — real historical options quotes aren't available for
  free. The backtester runs a real EMA20/50 crossover strategy on real
  historical Yahoo stock prices, then prices the hypothetical option leg
  with Black-Scholes seeded from trailing realized volatility. Every
  `/backtest` result documents this in its "Methodology" field. A
  strategy is only flagged `production_ready` once it has 20+ trades.

## Environment variables

Required:
- `DISCORD_BOT_TOKEN` — your Discord bot token.

Optional (enable a premium provider — see table above).

## Slash commands

| Command | Description |
|---|---|
| `/scan <ticker>` | Full AI trade decision: technicals, options, market context, news, trade plan |
| `/options <ticker>` | Options-chain analysis: greeks, IV rank, max pain, put/call ratio |
| `/news <ticker>` | News, sentiment, analyst actions, insider activity, SEC filings |
| `/earnings <ticker>` | Next earnings date and estimates |
| `/universe` | Universal scanner status: optionable-universe size, last refresh, top live candidates |
| `/history [ticker]` | Recent recommendations |
| `/performance` | Accuracy breakdown by ticker |
| `/stats` | Overall win rate and performance stats |
| `/portfolio` | Open positions with live unrealized P/L |
| `/backtest <ticker> [period]` | Backtest the EMA20/50 strategy on real price history |
| `/top` | Strategy leaderboard by learned win rate |
| `/alerts` | Recent auto-scan alerts |
| `/ping` | Health check |

## Background jobs

- **Universal market scanner (every 10 min, market hours)** — no hardcoded
  watchlist. The bot maintains a universe of every optionable US stock
  (official NASDAQ symbol directories ∩ CBOE options directory, refreshed
  daily at 08:15 UTC and cached in SQLite). Each cycle it prescreens a
  rotating 400-symbol slice with batched bulk downloads (price, %-change,
  volume-surge, dollar-volume floors — real bars only), keeps a ranked hot
  list across cycles, and runs the full V4 decision engine on the top 8
  fresh candidates. Only posts to a channel named `#trade-alerts` when the
  trade score is ≥ 80, liquidity ≥ 60, and risk/reward ≥ 2:1. If no
  `#trade-alerts` channel exists in any joined server, it logs a warning
  and skips posting (create the channel to receive alerts). If the symbol
  sources are unreachable, the scanner runs on the cached universe — and
  if no cache exists yet it skips the sweep and says so rather than
  scanning an invented list.
- **15-minute monitor** — re-prices every open recommendation's contract
  and closes it as a WIN or LOSS when it hits its take-profit, stop-loss,
  or expiration, feeding the result back into the self-learning strategy
  weights used by the confidence engine.

## Self-learning

Each recommendation is tagged with the technical/options/sentiment signals
that drove it (`core/database.py`'s `strategy_weights` table). When a trade
closes, its tags' weights nudge up (win) or down (loss) by 5%, bounded to
0.5–2.0. `/top` ranks tags by realized win rate once enough trades exist.

## Position sizing

Defaults to a $10,000 account, risking 2% per trade
(`core/risk.py`). Take-profit/stop levels are set so a filled trade plan
always clears a 2:1 minimum risk/reward.

## Logging

Console + rotating file at `discord-bot/logs/alphaoptionsai.log`.

## Scope notes

This build intentionally does not include a Redis cache, a web dashboard,
or a formal automated test suite — those were explicitly deferred. Every
module was smoke-tested manually against live Yahoo data instead.
