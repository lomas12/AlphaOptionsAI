"""Centralized logging for AlphaOptionsAI V3.

Logs API requests, errors, trade generation, backtests, and learning
updates to both the console (captured by the workflow) and a rotating file
under discord-bot/logs/.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger("alphaoptionsai")
    root.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = RotatingFileHandler(LOG_DIR / "alphaoptionsai.log", maxBytes=2_000_000, backupCount=3)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # yfinance logs a noisy "HTTP Error 404" line straight to its own logger
    # whenever a symbol has no fundamentals/earnings data (expected and
    # harmless for ETFs like SPY/QQQ/IWM) -- our code already catches these
    # and falls back gracefully, so quiet the library logger to ERROR only.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"alphaoptionsai.{name}")
