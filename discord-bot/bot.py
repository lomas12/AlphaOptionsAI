import os
import sys

import discord
from discord import app_commands

from core import ai_engine, alerts, backtester as backtester_module, bot_embeds, database, market_data as market_data_module, portfolio as portfolio_module
from core.logging_config import get_logger

logger = get_logger("bot")

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

if not TOKEN:
    print("Error: DISCORD_BOT_TOKEN environment variable is not set.", file=sys.stderr)
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True


class AlphaOptionsAIClient(discord.Client):
    def __init__(self, *, intents: discord.Intents) -> None:
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)


client = AlphaOptionsAIClient(intents=intents)


@client.tree.command(name="ping", description="Check if AlphaOptionsAI is online")
async def ping(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("🏓 Pong! AlphaOptionsAI is online.")


@client.tree.command(name="scan", description="AlphaOptionsAI V3: single best-trade decision for a ticker")
@app_commands.describe(ticker="Stock ticker symbol to scan, e.g. ORCL")
async def scan(interaction: discord.Interaction, ticker: str) -> None:
    await interaction.response.defer()
    try:
        decision = await ai_engine.analyze_ticker(ticker)
    except ai_engine.TickerNotFoundError as exc:
        await interaction.followup.send(str(exc))
        return
    except ai_engine.MarketDataUnavailableError as exc:
        logger.warning("Market data unavailable for %s: %s", ticker, exc)
        await interaction.followup.send(embed=bot_embeds.build_market_data_unavailable_embed(ticker.upper(), str(exc)))
        return
    except Exception:
        logger.exception("scan failed for %s", ticker)
        await interaction.followup.send(f"⚠️ Couldn't complete the scan for '{ticker.upper()}'. Please try again shortly.")
        return

    if decision.contract is not None:
        database.record_recommendation(
            ticker=decision.ticker, option_type=decision.contract["option_type"], strike=decision.contract["strike"],
            expiration=decision.contract["expiration"], entry_premium=decision.entry,
            take_profit_1=decision.take_profit_1, take_profit_2=decision.take_profit_2,
            stop_loss=decision.stop_loss, confidence=decision.confidence, risk_rating=decision.risk_rating,
            strategy_tags=decision.tags, source="manual",
        )
        logger.info("Recorded recommendation: %s %s %.1f%% confidence", decision.ticker, decision.recommendation, decision.confidence)

    await interaction.followup.send(embed=bot_embeds.build_trade_decision_embed(decision))


@client.tree.command(name="options", description="Full options-chain analysis for a ticker (greeks, IV rank, max pain, put/call ratio)")
@app_commands.describe(ticker="Stock ticker symbol, e.g. AAPL")
async def options_cmd(interaction: discord.Interaction, ticker: str) -> None:
    await interaction.response.defer()
    from apis import router
    from apis.yahoo import clean_ticker
    from core import options as options_module

    symbol = clean_ticker(ticker)
    try:
        verified_quote = market_data_module.get_verified_quote(symbol)
    except market_data_module.MarketDataUnavailableError as exc:
        logger.warning("Market data unavailable for %s: %s", symbol, exc)
        await interaction.followup.send(embed=bot_embeds.build_market_data_unavailable_embed(symbol, str(exc)))
        return

    history_result = router.get_history(symbol, period="1y")
    closes = history_result.value.df["Close"].dropna() if history_result.available else None
    chain_analysis = options_module.analyze_chain(symbol, verified_quote.price, closes)
    await interaction.followup.send(embed=bot_embeds.build_options_embed(symbol, chain_analysis, verified_quote))


@client.tree.command(name="news", description="Latest news, analyst actions, insider activity, and SEC filings for a ticker")
@app_commands.describe(ticker="Stock ticker symbol, e.g. TSLA")
async def news_cmd(interaction: discord.Interaction, ticker: str) -> None:
    await interaction.response.defer()
    from apis.yahoo import clean_ticker
    from core import news as news_module

    symbol = clean_ticker(ticker)
    news_ctx = news_module.get_ticker_news_context(symbol)
    await interaction.followup.send(embed=bot_embeds.build_news_embed(symbol, news_ctx))


@client.tree.command(name="earnings", description="Earnings calendar info for a ticker")
@app_commands.describe(ticker="Stock ticker symbol, e.g. NVDA")
async def earnings_cmd(interaction: discord.Interaction, ticker: str) -> None:
    await interaction.response.defer()
    from apis.yahoo import clean_ticker
    from core import earnings as earnings_module

    symbol = clean_ticker(ticker)
    earnings_ctx = earnings_module.get_earnings_context(symbol)
    await interaction.followup.send(embed=bot_embeds.build_earnings_embed(symbol, earnings_ctx))


@client.tree.command(name="watchlist", description="Show the automatic 5-minute scanner's watchlist")
async def watchlist_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=bot_embeds.build_watchlist_embed())


@client.tree.command(name="history", description="Show AlphaOptionsAI's most recent recommendations")
@app_commands.describe(ticker="Optional: filter by ticker")
async def history_cmd(interaction: discord.Interaction, ticker: str = None) -> None:
    from apis.yahoo import clean_ticker

    symbol = clean_ticker(ticker) if ticker else None
    rows = database.get_history(limit=10, ticker=symbol)
    await interaction.response.send_message(embed=bot_embeds.build_history_embed(rows, symbol))


@client.tree.command(name="performance", description="Show accuracy breakdown by ticker")
async def performance_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=bot_embeds.build_performance_embed())


@client.tree.command(name="stats", description="Show AlphaOptionsAI's overall performance stats")
async def stats_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=bot_embeds.build_stats_embed())


@client.tree.command(name="portfolio", description="Show open positions and their live unrealized P/L")
async def portfolio_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    positions = portfolio_module.get_open_portfolio()
    await interaction.followup.send(embed=bot_embeds.build_portfolio_embed(positions))


@client.tree.command(name="backtest", description="Backtest the EMA20/50 crossover strategy on a ticker's real price history")
@app_commands.describe(ticker="Stock ticker symbol, e.g. SPY", period="History window, e.g. 5y, 10y (default 5y)")
async def backtest_cmd(interaction: discord.Interaction, ticker: str, period: str = "5y") -> None:
    await interaction.response.defer()
    from apis.yahoo import clean_ticker

    symbol = clean_ticker(ticker)
    result = backtester_module.run_backtest(symbol, period=period)
    await interaction.followup.send(embed=bot_embeds.build_backtest_embed(symbol, result))


@client.tree.command(name="top", description="Leaderboard of the best performing strategy setups")
async def top_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=bot_embeds.build_top_embed())


@client.tree.command(name="alerts", description="Show recent auto-scan alerts posted to #trade-alerts")
async def alerts_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=bot_embeds.build_alerts_embed())


@client.event
async def on_ready():
    await client.tree.sync()
    alerts.register_background_tasks(client)
    print("Bot is online")
    print(f"Logged in as {client.user}")
    logger.info("Bot online as %s. Configured providers: %s", client.user, __import__("apis.router", fromlist=["configured_providers"]).configured_providers())


def main() -> None:
    client.run(TOKEN)


if __name__ == "__main__":
    main()
