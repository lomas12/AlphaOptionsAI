"""Background jobs for AlphaOptionsAI V2:

1. Every 15 minutes -- check each OPEN recommendation against the live
   option premium and close it out as a win or loss, feeding the result
   back into the learned strategy weights.
2. Every weekday morning -- scan the core watchlist and auto-post any
   trade with 80%+ confidence into #trade-alerts.
"""

import json
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import discord
import yfinance as yf
from discord.ext import tasks

MORNING_SCAN_TIME = time(hour=9, minute=35, tzinfo=ZoneInfo("America/New_York"))

import database
from trade_engine import analyze_ticker

MORNING_WATCHLIST = [
    "SPY", "QQQ", "NVDA", "TSM", "AMD", "MSFT", "GOOGL", "AMZN",
    "META", "AAPL", "TSLA", "ORCL", "PLTR", "CRWV", "IBIT",
]
AUTO_POST_CONFIDENCE_THRESHOLD = 80.0
TRADE_ALERTS_CHANNEL_NAME = "trade-alerts"


def _find_trade_alerts_channel(client: discord.Client) -> discord.TextChannel | None:
    for guild in client.guilds:
        for channel in guild.text_channels:
            if channel.name == TRADE_ALERTS_CHANNEL_NAME:
                return channel
    return None


def _get_live_contract_premium(ticker: str, expiration: str, strike: float, option_type: str) -> float | None:
    """Look up the current bid/ask mid (or last price) for one specific
    contract. Returns None if the contract can't be found or quoted."""
    try:
        tk = yf.Ticker(ticker)
        chain = tk.option_chain(expiration)
        df = chain.calls if option_type == "CALL" else chain.puts
        row = df[df["strike"] == strike]
        if row.empty:
            return None
        row = row.iloc[0]
        bid = float(row["bid"]) if row["bid"] == row["bid"] else 0.0
        ask = float(row["ask"]) if row["ask"] == row["ask"] else 0.0
        last_price = float(row["lastPrice"]) if row["lastPrice"] == row["lastPrice"] else 0.0
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        return last_price or None
    except Exception:
        return None


def _is_expired(expiration: str) -> bool:
    try:
        exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
        return exp_date < datetime.now(timezone.utc).date()
    except ValueError:
        return False


def check_open_recommendations_sync() -> list[str]:
    """Closes out any OPEN recommendation that has hit TP/SL/expiration.
    Returns a list of human-readable log lines for debugging."""
    logs: list[str] = []

    for rec in database.get_open_recommendations():
        current_premium = _get_live_contract_premium(
            rec["ticker"], rec["expiration"], rec["strike"], rec["option_type"]
        )

        status = None
        exit_premium = None

        if current_premium is not None:
            if current_premium >= rec["take_profit_2"]:
                status, exit_premium = "WIN_TP2", current_premium
            elif current_premium >= rec["take_profit_1"]:
                status, exit_premium = "WIN_TP1", current_premium
            elif current_premium <= rec["stop_loss"]:
                status, exit_premium = "LOSS", current_premium

        if status is None and _is_expired(rec["expiration"]):
            # Expired without hitting a target or stop -- settle at last known price.
            fallback_premium = current_premium if current_premium is not None else rec["entry_premium"]
            status = "WIN_TP1" if fallback_premium >= rec["entry_premium"] else "LOSS"
            exit_premium = fallback_premium

        if status is None:
            continue

        return_pct = round(((exit_premium - rec["entry_premium"]) / rec["entry_premium"]) * 100, 2)
        database.close_recommendation(rec["id"], status=status, exit_premium=exit_premium, return_pct=return_pct)

        won = status.startswith("WIN")
        tags = json.loads(rec["strategy_tags"])
        database.apply_learning(tags, won=won)

        logs.append(
            f"[AlphaOptionsAI] Closed #{rec['id']} {rec['ticker']} {rec['option_type']} -> {status} ({return_pct}%)"
        )

    return logs


def register_background_tasks(client: discord.Client) -> None:
    @tasks.loop(minutes=15)
    async def monitor_open_trades() -> None:
        import asyncio

        logs = await asyncio.to_thread(check_open_recommendations_sync)
        for line in logs:
            print(line)

    @tasks.loop(time=MORNING_SCAN_TIME)
    async def morning_scan() -> None:
        channel = _find_trade_alerts_channel(client)
        if channel is None:
            print(f"[AlphaOptionsAI] No #{TRADE_ALERTS_CHANNEL_NAME} channel found -- skipping morning scan post.")

        for ticker in MORNING_WATCHLIST:
            try:
                decision = await analyze_ticker(ticker)
            except Exception as exc:
                print(f"[AlphaOptionsAI] Morning scan failed for {ticker}: {exc}")
                continue

            if decision.recommendation == "NO TRADE" or decision.confidence < AUTO_POST_CONFIDENCE_THRESHOLD:
                continue

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
                source="morning_scan",
            )

            if channel is not None:
                from bot_embeds import build_trade_decision_embed

                await channel.send(embed=build_trade_decision_embed(decision))

    monitor_open_trades.start()
    morning_scan.start()
