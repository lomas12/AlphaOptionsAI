import os
import sys

import discord
from discord import app_commands

import database
from bot_embeds import (
    build_history_embed,
    build_performance_embed,
    build_stats_embed,
    build_top_embed,
    build_trade_decision_embed,
    build_watchlist_embed,
)
from market_data import TickerNotFoundError
from scheduler import MORNING_WATCHLIST, register_background_tasks
from trade_engine import NoOptionsAvailableError, analyze_ticker

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


@client.tree.command(name="scan", description="AlphaOptionsAI V2: single best-trade decision for a ticker")
@app_commands.describe(ticker="Stock ticker symbol to scan, e.g. ORCL")
async def scan(interaction: discord.Interaction, ticker: str) -> None:
    await interaction.response.defer()

    try:
        decision = await analyze_ticker(ticker)
    except TickerNotFoundError as exc:
        await interaction.followup.send(str(exc))
        return
    except NoOptionsAvailableError as exc:
        await interaction.followup.send(f"⚠️ {exc}")
        return
    except Exception:
        await interaction.followup.send(
            f"⚠️ Couldn't complete the scan for '{ticker.upper()}'. Please try again shortly."
        )
        return

    if decision.contract is not None:
        database.record_recommendation(
            ticker=decision.ticker,
            option_type=decision.contract.option_type,
            strike=decision.contract.strike,
            expiration=decision.contract.expiration,
            entry_premium=decision.entry,
            take_profit_1=decision.take_profit_1,
            take_profit_2=decision.take_profit_2,
            stop_loss=decision.stop_loss,
            confidence=decision.confidence,
            risk_rating=decision.risk_rating,
            strategy_tags=decision.contract.tags,
            source="manual",
        )

    await interaction.followup.send(embed=build_trade_decision_embed(decision))


@client.tree.command(name="stats", description="Show AlphaOptionsAI's overall performance stats")
async def stats(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=build_stats_embed())


@client.tree.command(name="history", description="Show AlphaOptionsAI's most recent recommendations")
async def history(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=build_history_embed())


@client.tree.command(name="watchlist", description="Show the morning scan watchlist")
async def watchlist(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=build_watchlist_embed(MORNING_WATCHLIST))


@client.tree.command(name="top", description="Leaderboard of the best performing strategy setups")
async def top(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=build_top_embed())


@client.tree.command(name="performance", description="Show accuracy breakdown by ticker")
async def performance(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=build_performance_embed())


_background_tasks_started = False


@client.event
async def on_ready():
    global _background_tasks_started
    await client.tree.sync()
    if not _background_tasks_started:
        register_background_tasks(client)
        _background_tasks_started = True
    print("Bot is online")
    print(f"Logged in as {client.user}")


def main() -> None:
    client.run(TOKEN)


if __name__ == "__main__":
    main()
