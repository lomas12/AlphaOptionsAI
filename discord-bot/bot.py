import os
import sys

import discord
from discord import app_commands

from market_data import ScanResult, TickerNotFoundError, get_scan_result
from options_scanner import ContractPick, NoOptionsAvailableError, OptionsScanResult, scan_options

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


def _build_scan_embed(result: ScanResult) -> discord.Embed:
    entry_price = result.current_price
    target_price = round(entry_price * 1.03, 2)
    stop_loss_price = round(entry_price * 0.98, 2)

    if result.trend == "Bullish":
        color = discord.Color.green()
    elif result.trend == "Bearish":
        color = discord.Color.red()
    else:
        color = discord.Color.light_grey()

    change_sign = "+" if result.daily_change_pct >= 0 else ""
    volume_ratio = (
        result.volume / result.avg_volume if result.avg_volume else 0
    )

    reasons = []
    if result.trend == "Bullish":
        reasons.append("• Price trading above 20 EMA")
    elif result.trend == "Bearish":
        reasons.append("• Price trading below 20 EMA")
    else:
        reasons.append("• Price consolidating near 20 EMA")
    reasons.append(
        "• Positive momentum" if result.daily_change_pct >= 0 else "• Negative momentum"
    )
    reasons.append(
        "• Volume above average" if volume_ratio > 1 else "• Volume below average"
    )

    embed = discord.Embed(title="📈 AlphaOptionsAI Scan", color=color)
    embed.add_field(name="Ticker", value=result.ticker, inline=True)
    embed.add_field(name="Trend", value=result.trend, inline=True)
    embed.add_field(name="AI Confidence", value=f"{result.confidence}%", inline=True)
    embed.add_field(name="Current Price", value=f"${entry_price:.2f}", inline=True)
    embed.add_field(name="Previous Close", value=f"${result.previous_close:.2f}", inline=True)
    embed.add_field(
        name="Daily Change",
        value=f"{change_sign}{result.daily_change_pct:.2f}%",
        inline=True,
    )
    embed.add_field(name="52-Week High", value=f"${result.high_52w:.2f}", inline=True)
    embed.add_field(name="52-Week Low", value=f"${result.low_52w:.2f}", inline=True)
    embed.add_field(name="Volume", value=f"{result.volume:,}", inline=True)
    embed.add_field(name="Avg Volume", value=f"{result.avg_volume:,.0f}", inline=True)
    embed.add_field(name="Entry", value=f"${entry_price:.2f}", inline=True)
    embed.add_field(name="Target", value=f"${target_price:.2f} (+3%)", inline=True)
    embed.add_field(name="Stop Loss", value=f"${stop_loss_price:.2f} (-2%)", inline=True)
    embed.add_field(name="Reason", value="\n".join(reasons), inline=False)
    embed.set_footer(text="AlphaOptionsAI Beta")

    return embed


def _build_contract_field_value(pick: ContractPick) -> str:
    return (
        f"Strike: **${pick.strike:.2f}**\n"
        f"Expiration: {pick.expiration}\n"
        f"Premium: ${pick.premium:.2f}\n"
        f"OI: {pick.open_interest:,}\n"
        f"Volume: {pick.volume:,}\n"
        f"IV: {pick.implied_vol * 100:.1f}%\n"
        f"AI Score: {pick.score:.0f}/100"
    )


def _build_options_embed(ticker: str, result: OptionsScanResult) -> discord.Embed:
    if result.risk == "Low":
        color = discord.Color.green()
    elif result.risk == "Medium":
        color = discord.Color.gold()
    else:
        color = discord.Color.red()

    embed = discord.Embed(title=f"🧠 AlphaOptionsAI Options Scan — {ticker}", color=color)
    embed.add_field(name="📈 Best Call", value=_build_contract_field_value(result.best_call), inline=True)
    embed.add_field(name="📉 Best Put", value=_build_contract_field_value(result.best_put), inline=True)
    embed.add_field(
        name="Expected Move",
        value=f"±${result.expected_move:.2f} ({result.expected_move_pct:.2f}%)",
        inline=True,
    )
    embed.add_field(name="Risk", value=result.risk, inline=True)
    embed.add_field(name="Win Probability", value=f"{result.win_probability:.1f}%", inline=True)
    embed.add_field(name="Suggested Entry", value=f"${result.entry:.2f}", inline=True)
    embed.add_field(name="Suggested Exit", value=f"${result.exit_target:.2f}", inline=True)
    embed.add_field(name="Suggested Stop Loss", value=f"${result.stop_loss:.2f}", inline=True)
    embed.set_footer(text="AlphaOptionsAI Beta • Not financial advice")

    return embed


@client.tree.command(name="scan", description="Run an AlphaOptionsAI scan on a ticker")
@app_commands.describe(ticker="Stock ticker symbol to scan, e.g. ORCL")
async def scan(interaction: discord.Interaction, ticker: str) -> None:
    await interaction.response.defer()

    try:
        result = await get_scan_result(ticker)
    except TickerNotFoundError as exc:
        await interaction.followup.send(f"⚠️ {exc}")
        return
    except Exception:
        await interaction.followup.send(
            f"⚠️ Couldn't fetch market data for '{ticker.upper()}'. Please try again shortly."
        )
        return

    embeds = [_build_scan_embed(result)]

    try:
        options_result = await scan_options(result.ticker, result.current_price)
        embeds.append(_build_options_embed(result.ticker, options_result))
    except NoOptionsAvailableError as exc:
        embeds[0].add_field(name="Options Scan", value=f"⚠️ {exc}", inline=False)
    except Exception:
        embeds[0].add_field(
            name="Options Scan",
            value="⚠️ Couldn't fetch the options chain right now. Please try again shortly.",
            inline=False,
        )

    await interaction.followup.send(embeds=embeds)


@client.event
async def on_ready():
    await client.tree.sync()
    print("Bot is online")
    print(f"Logged in as {client.user}")


def main() -> None:
    client.run(TOKEN)


if __name__ == "__main__":
    main()
