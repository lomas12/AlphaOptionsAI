"""Discord embed builders for AlphaOptionsAI V3."""

from datetime import datetime, timezone

import discord

from core import ai_engine, backtester as backtester_module, database, portfolio as portfolio_module

COLOR_CALL = discord.Color.green()
COLOR_PUT = discord.Color.red()
COLOR_NEUTRAL = discord.Color.light_grey()

UNAVAILABLE = "Data unavailable from API"


def _fmt(value, suffix: str = "", decimals: int = 2) -> str:
    if value is None:
        return UNAVAILABLE
    if isinstance(value, float):
        return f"{value:.{decimals}f}{suffix}"
    return f"{value}{suffix}"


def _color_for(recommendation: str) -> discord.Color:
    if recommendation == "BUY CALL":
        return COLOR_CALL
    if recommendation == "BUY PUT":
        return COLOR_PUT
    return COLOR_NEUTRAL


def build_trade_decision_embed(decision: ai_engine.TradeDecision) -> discord.Embed:
    banner = {"BUY CALL": "🟢 BUY CALL", "BUY PUT": "🔴 BUY PUT", "NO TRADE": "⚪ NO TRADE"}[decision.recommendation]

    as_of_text = decision.price_as_of.strftime("%Y-%m-%d %H:%M:%S UTC") if decision.price_as_of else "unknown"
    embed = discord.Embed(
        title=f"{decision.ticker} — {banner}",
        description=f"Current Price: **${decision.price:.2f}**  (source: {decision.price_source}, as of {as_of_text})",
        color=_color_for(decision.recommendation),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Confidence", value=f"{decision.confidence:.1f}%", inline=True)
    if decision.risk_rating:
        embed.add_field(name="Risk Rating", value=decision.risk_rating, inline=True)
    if decision.chain_analysis and decision.chain_analysis.expected_move:
        embed.add_field(
            name="Expected Move",
            value=f"±${decision.chain_analysis.expected_move:.2f} ({decision.chain_analysis.expected_move_pct:.1f}%)",
            inline=True,
        )

    embed.add_field(name="Reasoning", value="\n".join(f"• {r}" for r in decision.reasoning[:8]), inline=False)

    if decision.contract:
        c = decision.contract
        embed.add_field(
            name="Recommended Contract",
            value=(
                f"{c['option_type']} ${c['strike']} exp {c['expiration']} ({c['dte']}d)\n"
                f"Premium: ${c['premium']:.2f} | IV: {c['implied_vol']*100:.1f}% | OI: {c['open_interest']} | Vol: {c['volume']}\n"
                f"Δ {c['delta']:.3f} | Γ {c['gamma']:.4f} | Θ {c['theta']:.3f} | Vega {c['vega']:.3f}\n"
                f"Probability ITM: {c['probability_itm']:.1f}%"
                + (" | ⚡ Unusual Activity" if c["unusual_activity"] else "")
            ),
            inline=False,
        )
        embed.add_field(
            name="Trade Plan",
            value=(
                f"Entry: ${decision.entry:.2f}\n"
                f"TP1: ${decision.take_profit_1:.2f} | TP2: ${decision.take_profit_2:.2f}\n"
                f"Stop Loss: ${decision.stop_loss:.2f}\n"
                f"Risk/Reward: {decision.risk_reward_ratio}:1\n"
                f"Dollar Risk/Contract: ${decision.dollar_risk_per_contract:.2f}\n"
                f"Suggested Size: {decision.position_size_contracts} contract(s) "
                f"(2% of ${decision.account_balance:,.0f} account)"
            ),
            inline=False,
        )
    elif decision.recommendation == "NO TRADE" and decision.chain_analysis:
        best_call = max(decision.chain_analysis.calls, key=lambda c: c.liquidity_score, default=None)
        best_put = max(decision.chain_analysis.puts, key=lambda p: p.liquidity_score, default=None)
        alt_lines = []
        if best_call:
            alt_lines.append(f"CALL ${best_call.contract.strike} exp {best_call.contract.expiration} -- liquidity {best_call.liquidity_score}")
        if best_put:
            alt_lines.append(f"PUT ${best_put.contract.strike} exp {best_put.contract.expiration} -- liquidity {best_put.liquidity_score}")
        if alt_lines:
            embed.add_field(name="Alternative Trade (below 70% confidence)", value="\n".join(alt_lines), inline=False)

    if decision.chain_analysis:
        ca = decision.chain_analysis
        embed.add_field(
            name="Options Context",
            value=(
                f"Max Pain: {_fmt(ca.max_pain, '$', 2) if ca.max_pain is None else f'${ca.max_pain:.2f}'}\n"
                f"Put/Call Ratio: {_fmt(ca.put_call_ratio)}\n"
                f"IV Rank: {_fmt(ca.iv_rank, '%', 1)} | IV Percentile: {_fmt(ca.iv_percentile, '%', 1)}"
            ),
            inline=False,
        )

    market = decision.market
    sentiment = decision.news_context.news_sentiment or "N/A"
    footer_lines = [
        f"SPY {market.spy_trend or 'N/A'} | QQQ {market.qqq_trend or 'N/A'} | VIX {_fmt(market.vix_level, '', 1)} ({market.vix_classification or 'N/A'})",
        f"News sentiment: {sentiment}",
    ]
    if decision.missing_data:
        footer_lines.append(f"Unavailable: {', '.join(decision.missing_data)}")
    embed.set_footer(text=" | ".join(footer_lines))
    return embed


def build_options_embed(ticker: str, chain_analysis, verified_quote=None) -> discord.Embed:
    embed = discord.Embed(title=f"{ticker} — Options Analysis", color=discord.Color.blurple(), timestamp=datetime.now(timezone.utc))
    if verified_quote is not None:
        as_of_text = verified_quote.as_of.strftime("%Y-%m-%d %H:%M:%S UTC") if verified_quote.as_of else "unknown"
        embed.description = f"Current Price: **${verified_quote.price:.2f}**  (source: {verified_quote.source}, as of {as_of_text})"
    if chain_analysis is None:
        embed.description = (embed.description + "\n\n" if embed.description else "") + UNAVAILABLE
        return embed

    embed.add_field(name="Expected Move", value=f"±${chain_analysis.expected_move:.2f} ({chain_analysis.expected_move_pct:.1f}%)", inline=True)
    embed.add_field(name="Max Pain", value=_fmt(chain_analysis.max_pain, "$"), inline=True)
    embed.add_field(name="Put/Call Ratio", value=_fmt(chain_analysis.put_call_ratio), inline=True)
    embed.add_field(name="IV Rank", value=_fmt(chain_analysis.iv_rank, "%", 1), inline=True)
    embed.add_field(name="IV Percentile", value=_fmt(chain_analysis.iv_percentile, "%", 1), inline=True)

    top_calls = sorted(chain_analysis.calls, key=lambda c: c.liquidity_score, reverse=True)[:3]
    top_puts = sorted(chain_analysis.puts, key=lambda p: p.liquidity_score, reverse=True)[:3]
    if top_calls:
        embed.add_field(
            name="Top Calls (by liquidity)",
            value="\n".join(f"${c.contract.strike} exp {c.contract.expiration} | liq {c.liquidity_score} | ITM% {c.probability_itm}" for c in top_calls),
            inline=False,
        )
    if top_puts:
        embed.add_field(
            name="Top Puts (by liquidity)",
            value="\n".join(f"${p.contract.strike} exp {p.contract.expiration} | liq {p.liquidity_score} | ITM% {p.probability_itm}" for p in top_puts),
            inline=False,
        )
    embed.set_footer(text=f"Source: {chain_analysis.source}")
    return embed


def build_news_embed(ticker: str, news_ctx) -> discord.Embed:
    embed = discord.Embed(title=f"{ticker} — News & Sentiment", color=discord.Color.blurple(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Sentiment", value=news_ctx.news_sentiment or UNAVAILABLE, inline=True)
    if news_ctx.analyst_action and news_ctx.analyst_action.action:
        a = news_ctx.analyst_action
        embed.add_field(name="Latest Analyst Action", value=f"{a.action} by {a.firm or 'Unknown'} ({a.from_grade or '?'} → {a.to_grade or '?'})", inline=False)
    if news_ctx.news_items:
        embed.add_field(name="Recent Headlines", value="\n".join(f"• {n.title}" for n in news_ctx.news_items[:5]), inline=False)
    else:
        embed.add_field(name="Recent Headlines", value=UNAVAILABLE, inline=False)
    if news_ctx.insider_transactions:
        embed.add_field(
            name="Insider Activity",
            value="\n".join(f"{t.insider}: {t.transaction_type} ({t.shares:,.0f} sh)" for t in news_ctx.insider_transactions[:5]),
            inline=False,
        )
    if news_ctx.sec_filings:
        embed.add_field(name="Recent SEC Filings", value="\n".join(f"{f.filing_type} — {f.filing_date}" for f in news_ctx.sec_filings[:5]), inline=False)
    return embed


def build_earnings_embed(ticker: str, earnings_ctx) -> discord.Embed:
    embed = discord.Embed(title=f"{ticker} — Earnings", color=discord.Color.blurple(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Earnings Date", value=earnings_ctx.earnings_date or UNAVAILABLE, inline=True)
    embed.add_field(name="Days to Earnings", value=str(earnings_ctx.days_to_earnings) if earnings_ctx.days_to_earnings is not None else UNAVAILABLE, inline=True)
    embed.add_field(name="EPS Estimate", value=_fmt(earnings_ctx.eps_estimate), inline=True)
    embed.add_field(name="Revenue Estimate", value=_fmt(earnings_ctx.revenue_estimate, decimals=0), inline=True)
    return embed


def build_watchlist_embed() -> discord.Embed:
    tickers = database.get_watchlist()
    embed = discord.Embed(title="📋 AlphaOptionsAI Watchlist", description="\n".join(tickers), color=discord.Color.blurple())
    return embed


def build_stats_embed() -> discord.Embed:
    stats = database.get_overall_stats()
    embed = discord.Embed(title="📊 Overall Performance", color=discord.Color.blurple(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Total Closed Trades", value=str(stats.total_trades), inline=True)
    embed.add_field(name="Open Trades", value=str(stats.open_trades), inline=True)
    embed.add_field(name="Win Rate", value=f"{stats.win_rate}%", inline=True)
    embed.add_field(name="Wins / Losses", value=f"{stats.wins} / {stats.losses}", inline=True)
    embed.add_field(name="Avg Return", value=f"{stats.avg_return_pct}%", inline=True)
    embed.add_field(name="Profit Factor", value=_fmt(stats.profit_factor), inline=True)
    return embed


def build_history_embed(rows, ticker: str | None) -> discord.Embed:
    title = f"📜 Trade History — {ticker}" if ticker else "📜 Trade History"
    embed = discord.Embed(title=title, color=discord.Color.blurple(), timestamp=datetime.now(timezone.utc))
    if not rows:
        embed.description = "No trades recorded yet."
        return embed
    for row in rows:
        status_emoji = {"OPEN": "🟡", "WIN": "🟢", "LOSS": "🔴"}.get(row["status"].split("_")[0] if row["status"] else "OPEN", "⚪")
        embed.add_field(
            name=f"{status_emoji} {row['ticker']} {row['option_type']} ${row['strike']} exp {row['expiration']}",
            value=f"Status: {row['status']} | Entry ${row['entry_premium']:.2f}" + (f" | Return {row['return_pct']:.1f}%" if row["return_pct"] is not None else ""),
            inline=False,
        )
    return embed


def build_performance_embed() -> discord.Embed:
    rows = database.get_accuracy_by_ticker()
    embed = discord.Embed(title="🎯 Accuracy by Ticker", color=discord.Color.blurple(), timestamp=datetime.now(timezone.utc))
    if not rows:
        embed.description = "No closed trades yet."
        return embed
    for row in rows[:15]:
        win_rate = round((row["wins"] / row["total"]) * 100, 1) if row["total"] else 0
        embed.add_field(name=row["ticker"], value=f"{row['wins']}/{row['total']} wins ({win_rate}%) | avg return {row['avg_return']}%", inline=False)
    return embed


def build_top_embed() -> discord.Embed:
    leaderboard = database.get_accuracy_by_strategy()
    embed = discord.Embed(title="🏆 Strategy Leaderboard", color=discord.Color.gold(), timestamp=datetime.now(timezone.utc))
    if not leaderboard:
        embed.description = "Not enough closed trades yet to rank strategies."
        return embed
    lines = [f"**{i+1}. {s['tag']}** — {s['win_rate']}% win rate over {s['total']} trades (avg {s['avg_return']}%)" for i, s in enumerate(leaderboard[:10])]
    embed.description = "\n".join(lines)
    return embed


def build_portfolio_embed(positions) -> discord.Embed:
    embed = discord.Embed(title="💼 Open Portfolio", color=discord.Color.blurple(), timestamp=datetime.now(timezone.utc))
    if not positions:
        embed.description = "No open positions."
        return embed
    for p in positions:
        pl_text = f"{p.unrealized_pct:+.1f}%" if p.unrealized_pct is not None else UNAVAILABLE
        embed.add_field(
            name=f"{p.ticker} {p.option_type} ${p.strike} exp {p.expiration}",
            value=f"Entry ${p.entry_premium:.2f} → Current {'$'+format(p.current_premium, '.2f') if p.current_premium else UNAVAILABLE} ({pl_text}) | Confidence {p.confidence:.1f}%",
            inline=False,
        )
    return embed


def build_backtest_embed(ticker: str, result) -> discord.Embed:
    embed = discord.Embed(title=f"🔬 Backtest — {ticker} (EMA20/50 Crossover)", color=discord.Color.blurple(), timestamp=datetime.now(timezone.utc))
    if result is None:
        embed.description = "Not enough historical data to run a backtest for this ticker."
        return embed

    embed.add_field(name="Period", value=result.period, inline=True)
    embed.add_field(name="Total Trades", value=str(result.total_trades), inline=True)
    embed.add_field(name="Production Ready", value="✅ Yes" if result.production_ready else f"⚠️ No (needs {backtester_module.MIN_TRADES_FOR_PRODUCTION}+ trades)", inline=True)
    embed.add_field(name="Win Rate", value=_fmt(result.win_rate, "%", 1), inline=True)
    embed.add_field(name="Avg Return", value=_fmt(result.avg_return_pct, "%", 2), inline=True)
    embed.add_field(name="Avg Hold", value=_fmt(result.avg_hold_days, "d", 1), inline=True)
    embed.add_field(name="Max Drawdown", value=_fmt(result.max_drawdown_pct, "%", 2), inline=True)
    embed.add_field(name="Max Gain", value=_fmt(result.max_gain_pct, "%", 2), inline=True)
    embed.add_field(name="Sharpe Ratio", value=_fmt(result.sharpe_ratio), inline=True)
    embed.add_field(name="Sortino Ratio", value=_fmt(result.sortino_ratio), inline=True)
    embed.add_field(name="Profit Factor", value=_fmt(result.profit_factor), inline=True)
    embed.add_field(name="Expectancy", value=_fmt(result.expectancy, "%", 2), inline=True)
    embed.add_field(name="Methodology", value=result.methodology_note, inline=False)
    return embed


def build_market_data_unavailable_embed(ticker: str, reason: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{ticker} — Market data unavailable",
        description=(
            "A verified, current price for this ticker could not be confirmed, "
            "so no trade recommendation was generated.\n\n"
            f"Reason: {reason}"
        ),
        color=COLOR_NEUTRAL,
        timestamp=datetime.now(timezone.utc),
    )
    return embed


def build_alerts_embed() -> discord.Embed:
    rows = database.get_recent_alerts(10)
    embed = discord.Embed(title="🚨 Recent Auto-Scan Alerts", color=discord.Color.gold(), timestamp=datetime.now(timezone.utc))
    if not rows:
        embed.description = "No alerts posted yet."
        return embed
    for row in rows:
        embed.add_field(name=f"{row['ticker']} — {row['message']}", value=f"Confidence {row['confidence']:.1f}% | {row['created_at'][:19]}", inline=False)
    return embed
