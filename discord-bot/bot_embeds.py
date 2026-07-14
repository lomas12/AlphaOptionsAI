"""Discord embed builders for AlphaOptionsAI V2 commands."""

import discord

import database
from trade_engine import TradeDecision


def build_trade_decision_embed(decision: TradeDecision) -> discord.Embed:
    if decision.recommendation == "BUY CALL":
        headline, color = "🟢 Recommendation\nBUY CALL", discord.Color.green()
    elif decision.recommendation == "BUY PUT":
        headline, color = "🔴 Recommendation\nBUY PUT", discord.Color.red()
    else:
        headline, color = "⚪ NO TRADE", discord.Color.light_grey()

    embed = discord.Embed(title=f"AlphaOptionsAI V2 — {decision.ticker}", description=headline, color=color)
    embed.add_field(name="Confidence", value=f"{decision.confidence:.0f}%", inline=True)

    if decision.contract:
        embed.add_field(name="Risk Rating", value=decision.risk_rating, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

    embed.add_field(name="Reasoning", value="\n".join(f"• {r}" for r in decision.reasoning), inline=False)

    if decision.contract:
        c = decision.contract
        embed.add_field(
            name="Recommended Contract",
            value=(
                f"Ticker: **{decision.ticker}**\n"
                f"Strike: ${c.strike:.2f}\n"
                f"Expiration: {c.expiration}\n"
                f"Current Premium: ${c.premium:.2f}\n"
                f"Open Interest: {c.open_interest:,}\n"
                f"Volume: {c.volume:,}\n"
                f"Implied Volatility: {c.implied_vol * 100:.1f}%\n"
                f"Delta: {c.delta:.3f}\n"
                f"Gamma: {c.gamma:.4f}\n"
                f"Theta: {c.theta:.3f}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Trade Plan",
            value=(
                f"Entry: ${decision.entry:.2f}\n"
                f"Take Profit 1: ${decision.take_profit_1:.2f}\n"
                f"Take Profit 2: ${decision.take_profit_2:.2f}\n"
                f"Stop Loss: ${decision.stop_loss:.2f}\n"
                f"Max Risk: ${decision.max_risk_dollars:.2f}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Probability",
            value=(
                f"Chance of reaching TP1: {decision.prob_tp1:.0f}%\n"
                f"Chance of reaching TP2: {decision.prob_tp2:.0f}%"
            ),
            inline=False,
        )
        embed.add_field(
            name="Position Size",
            value=(
                f"Risking 1-2% of a ${decision.account_balance:,.0f} account "
                f"(≈${decision.max_risk_dollars:,.0f})\n"
                f"Suggested size: **{decision.position_size_contracts} contract(s)**"
            ),
            inline=False,
        )
    else:
        embed.add_field(
            name="Alternative Trade",
            value="Confidence is below 70% -- wait for confirmation before entering.",
            inline=False,
        )

    market = decision.market
    if market.vix_level is not None:
        market_value = (
            f"SPY: {market.spy_trend or 'N/A'} · QQQ: {market.qqq_trend or 'N/A'} · "
            f"VIX: {market.vix_level:.1f} ({market.vix_classification})"
        )
    else:
        market_value = f"SPY: {market.spy_trend or 'N/A'} · QQQ: {market.qqq_trend or 'N/A'} · VIX: N/A"
    embed.add_field(name="Market Context", value=market_value, inline=False)
    embed.set_footer(text="AlphaOptionsAI V2 • Not financial advice")
    return embed


def build_stats_embed() -> discord.Embed:
    stats = database.get_overall_stats()
    embed = discord.Embed(title="📊 AlphaOptionsAI Performance Stats", color=discord.Color.blurple())
    embed.add_field(name="Total Closed Trades", value=str(stats.total_trades), inline=True)
    embed.add_field(name="Open Trades", value=str(stats.open_trades), inline=True)
    embed.add_field(name="Win Rate", value=f"{stats.win_rate}%", inline=True)
    embed.add_field(name="Wins / Losses", value=f"{stats.wins} / {stats.losses}", inline=True)
    embed.add_field(name="Avg Return", value=f"{stats.avg_return_pct}%", inline=True)
    embed.add_field(
        name="Profit Factor",
        value=str(stats.profit_factor) if stats.profit_factor is not None else "N/A",
        inline=True,
    )
    embed.set_footer(text="AlphaOptionsAI V2")
    return embed


def build_history_embed(limit: int = 10) -> discord.Embed:
    rows = database.get_history(limit=limit)
    embed = discord.Embed(title="🕘 Recent Recommendations", color=discord.Color.blurple())
    if not rows:
        embed.description = "No recommendations recorded yet."
        return embed

    lines = []
    for row in rows:
        status_emoji = {"OPEN": "🟡", "WIN_TP1": "✅", "WIN_TP2": "✅", "LOSS": "❌"}.get(row["status"], "•")
        ret = f"{row['return_pct']:+.1f}%" if row["return_pct"] is not None else "—"
        lines.append(
            f"{status_emoji} **{row['ticker']}** {row['option_type']} ${row['strike']:.2f} "
            f"({row['expiration']}) — {row['status']} {ret}"
        )
    embed.description = "\n".join(lines)
    embed.set_footer(text="AlphaOptionsAI V2")
    return embed


def build_watchlist_embed(watchlist: list[str]) -> discord.Embed:
    embed = discord.Embed(title="👀 AlphaOptionsAI Morning Watchlist", color=discord.Color.blurple())
    embed.description = ", ".join(watchlist)
    embed.set_footer(text="Scanned every morning • 80%+ confidence trades auto-post to #trade-alerts")
    return embed


def build_top_embed(limit: int = 10) -> discord.Embed:
    leaderboard = database.get_accuracy_by_strategy()[:limit]
    embed = discord.Embed(title="🏆 Strategy Leaderboard", color=discord.Color.gold())
    if not leaderboard:
        embed.description = "Not enough closed trades yet to rank strategies."
        return embed

    lines = [
        f"**{i + 1}. {entry['tag']}** — {entry['win_rate']}% win rate over {entry['total']} trades "
        f"(avg {entry['avg_return']:+.1f}%)"
        for i, entry in enumerate(leaderboard)
    ]
    embed.description = "\n".join(lines)
    embed.set_footer(text="AlphaOptionsAI V2 • Self-learning strategy weights")
    return embed


def build_performance_embed() -> discord.Embed:
    by_ticker = database.get_accuracy_by_ticker()
    embed = discord.Embed(title="📈 Accuracy by Ticker", color=discord.Color.blurple())
    if not by_ticker:
        embed.description = "Not enough closed trades yet."
        return embed

    lines = [
        f"**{row['ticker']}** — {row['wins']}/{row['total']} wins, avg return {row['avg_return']:+.1f}%"
        for row in by_ticker[:15]
    ]
    embed.description = "\n".join(lines)
    embed.set_footer(text="AlphaOptionsAI V2")
    return embed
