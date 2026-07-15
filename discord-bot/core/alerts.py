"""Background jobs: 5-minute watchlist scanner, 15-minute open-trade
monitor (win/loss + self-learning), and posting qualifying trades to
#trade-alerts. Registered once from bot.py's on_ready.
"""

import logging
from datetime import date, datetime

import discord
from discord.ext import tasks

from apis import router
from core import ai_engine, database, scanner as scanner_module

logger = logging.getLogger("alphaoptionsai.alerts")

TRADE_ALERTS_CHANNEL_NAME = "trade-alerts"
SCAN_INTERVAL_MINUTES = 5
MONITOR_INTERVAL_MINUTES = 15

_background_tasks_started = False


def _find_trade_alerts_channel(client: discord.Client) -> discord.TextChannel | None:
    for guild in client.guilds:
        for channel in guild.text_channels:
            if channel.name == TRADE_ALERTS_CHANNEL_NAME:
                return channel
    return None


def _is_expired(expiration: str) -> bool:
    try:
        return datetime.strptime(expiration, "%Y-%m-%d").date() < date.today()
    except ValueError:
        return False


def check_open_recommendations_sync() -> None:
    for rec in database.get_open_recommendations():
        chain_result = router.get_option_chain(rec["ticker"], rec["expiration"])
        if not chain_result.available:
            continue
        chain = chain_result.value
        contracts = chain.calls if rec["option_type"] == "CALL" else chain.puts
        match = next((c for c in contracts if abs(c.strike - rec["strike"]) < 0.01), None)
        if match is None:
            continue

        current_premium = (match.bid + match.ask) / 2 if match.bid > 0 and match.ask > 0 else match.last_price
        if current_premium <= 0:
            continue

        entry = rec["entry_premium"]
        return_pct = round((current_premium - entry) / entry * 100, 2)
        expired = _is_expired(rec["expiration"])

        hit_tp = current_premium >= rec["take_profit_1"]
        hit_sl = current_premium <= rec["stop_loss"]

        if not (hit_tp or hit_sl or expired):
            continue

        won = return_pct > 0 if expired else hit_tp
        status = "WIN" if won else "LOSS"

        database.close_recommendation(
            rec["id"], status=status, exit_premium=round(current_premium, 2), return_pct=return_pct,
        )
        try:
            import json
            tags = json.loads(rec["strategy_tags"])
            database.apply_learning(tags, won=won)
        except Exception as exc:
            logger.warning("Failed to apply learning for recommendation %s: %s", rec["id"], exc)

        logger.info("Closed recommendation #%s (%s %s): %s (%.2f%%)", rec["id"], rec["ticker"], rec["option_type"], status, return_pct)


async def _run_scan_and_maybe_alert(client: discord.Client, ticker: str) -> None:
    try:
        decision = await ai_engine.analyze_ticker(ticker)
    except ai_engine.TickerNotFoundError:
        return
    except Exception as exc:
        logger.warning("Auto-scan failed for %s: %s", ticker, exc)
        return

    result = scanner_module.evaluate_for_auto_post(decision)
    if not result.qualifies:
        return

    channel = _find_trade_alerts_channel(client)
    if channel is None:
        logger.warning("No #%s channel found -- skipping alert post for %s.", TRADE_ALERTS_CHANNEL_NAME, ticker)
        return

    from core import bot_embeds  # local import: avoids a circular import at module load time

    contract = decision.contract
    rec_id = database.record_recommendation(
        ticker=decision.ticker, option_type=contract["option_type"], strike=contract["strike"],
        expiration=contract["expiration"], entry_premium=decision.entry,
        take_profit_1=decision.take_profit_1, take_profit_2=decision.take_profit_2,
        stop_loss=decision.stop_loss, confidence=decision.confidence, risk_rating=decision.risk_rating,
        strategy_tags=decision.tags, source="auto_scan",
    )
    embed = bot_embeds.build_trade_decision_embed(decision)
    await channel.send(content="🚨 **High-confidence auto-scan alert**", embed=embed)
    database.record_alert(
        ticker=decision.ticker, recommendation_id=rec_id, confidence=decision.confidence,
        channel=channel.name, message=decision.recommendation,
    )
    logger.info("Posted auto-scan alert for %s (%.1f%% confidence)", decision.ticker, decision.confidence)


def register_background_tasks(client: discord.Client) -> None:
    global _background_tasks_started
    if _background_tasks_started:
        return
    _background_tasks_started = True

    @tasks.loop(minutes=MONITOR_INTERVAL_MINUTES)
    async def monitor_open_trades() -> None:
        try:
            check_open_recommendations_sync()
        except Exception as exc:
            logger.error("monitor_open_trades failed: %s", exc)

    @tasks.loop(minutes=SCAN_INTERVAL_MINUTES)
    async def five_minute_scanner() -> None:
        watchlist = database.get_watchlist()
        for ticker in watchlist:
            await _run_scan_and_maybe_alert(client, ticker)

    monitor_open_trades.start()
    five_minute_scanner.start()
    logger.info("Background tasks started: monitor_open_trades (every %sm), five_minute_scanner (every %sm)", MONITOR_INTERVAL_MINUTES, SCAN_INTERVAL_MINUTES)
