import os
import random
import sys

import discord
from discord import app_commands

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


@client.tree.command(name="scan", description="Run an AlphaOptionsAI scan on a ticker")
@app_commands.describe(ticker="Stock ticker symbol to scan, e.g. ORCL")
async def scan(interaction: discord.Interaction, ticker: str) -> None:
    ticker = ticker.upper()

    trend = random.choice(["Bullish", "Bearish", "Neutral"])
    confidence = round(random.uniform(55, 95), 1)

    # Placeholder entry price until a real market data source is wired up.
    entry_price = round(random.uniform(20, 500), 2)

    target_price = round(entry_price * 1.03, 2)
    stop_loss_price = round(entry_price * 0.98, 2)

    if trend == "Bullish":
        color = discord.Color.green()
    elif trend == "Bearish":
        color = discord.Color.red()
    else:
        color = discord.Color.light_grey()

    embed = discord.Embed(title="📈 AlphaOptionsAI Scan", color=color)
    embed.add_field(name="Ticker", value=ticker, inline=True)
    embed.add_field(name="Trend", value=trend, inline=True)
    embed.add_field(name="AI Confidence", value=f"{confidence}%", inline=True)
    embed.add_field(name="Entry", value=f"${entry_price}", inline=True)
    embed.add_field(name="Target", value=f"${target_price} (+3%)", inline=True)
    embed.add_field(name="Stop Loss", value=f"${stop_loss_price} (-2%)", inline=True)
    embed.add_field(
        name="Reason",
        value="• Trend above moving averages\n• Positive momentum\n• Healthy volume",
        inline=False,
    )
    embed.set_footer(text="AlphaOptionsAI Beta")

    await interaction.response.send_message(embed=embed)


@client.event
async def on_ready():
    await client.tree.sync()
    print("Bot is online")
    print(f"Logged in as {client.user}")


def main() -> None:
    client.run(TOKEN)


if __name__ == "__main__":
    main()
