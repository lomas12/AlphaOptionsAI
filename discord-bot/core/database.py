"""SQLite persistence for AlphaOptionsAI V3: trades (recommendations),
backtests, alerts, watchlists, performance snapshots, API logs, and
self-learning strategy weights.
"""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

DB_PATH = Path(__file__).parent.parent / "alphaoptionsai.db"

MIN_WEIGHT = 0.5
MAX_WEIGHT = 2.0
WIN_MULTIPLIER = 1.05
LOSS_MULTIPLIER = 0.95

DEFAULT_TAGS = [
    "trend_stack_bullish", "trend_stack_bearish", "above_ema50", "below_ema50",
    "rsi_bullish", "rsi_bearish", "rsi_overbought", "rsi_oversold",
    "macd_bullish", "macd_bearish", "adx_strong_trend", "supertrend_bullish",
    "supertrend_bearish", "volume_confirmation", "high_relative_volume",
    "room_to_resistance", "room_to_support", "resistance_overhead", "support_below",
    "bullish_breakout", "bearish_breakdown", "market_trend_aligned", "market_trend_against",
    "vix_supportive", "vix_elevated", "positive_news_sentiment", "negative_news_sentiment",
    "analyst_upgrade", "analyst_downgrade", "insider_buying", "insider_selling",
    "earnings_event_risk", "unusual_options_activity", "relative_strength_positive",
    "relative_strength_negative",
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                option_type TEXT NOT NULL,
                strike REAL NOT NULL,
                expiration TEXT NOT NULL,
                entry_premium REAL NOT NULL,
                take_profit_1 REAL NOT NULL,
                take_profit_2 REAL NOT NULL,
                stop_loss REAL NOT NULL,
                confidence REAL NOT NULL,
                risk_rating TEXT NOT NULL,
                strategy_tags TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                sector TEXT,
                status TEXT NOT NULL DEFAULT 'OPEN',
                closed_at TEXT,
                exit_premium REAL,
                max_gain_pct REAL,
                max_drawdown_pct REAL,
                return_pct REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_weights (
                tag TEXT PRIMARY KEY,
                weight REAL NOT NULL DEFAULT 1.0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backtests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                strategy_tag TEXT NOT NULL,
                period TEXT NOT NULL,
                total_trades INTEGER NOT NULL,
                win_rate REAL,
                avg_return_pct REAL,
                avg_hold_days REAL,
                max_drawdown_pct REAL,
                max_gain_pct REAL,
                sharpe_ratio REAL,
                sortino_ratio REAL,
                profit_factor REAL,
                expectancy REAL,
                methodology_note TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                recommendation_id INTEGER,
                confidence REAL NOT NULL,
                channel TEXT,
                message TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                tickers TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS performance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                period TEXT NOT NULL,
                total_trades INTEGER,
                win_rate REAL,
                avg_return_pct REAL,
                profit_factor REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                provider TEXT NOT NULL,
                capability TEXT NOT NULL,
                symbol TEXT,
                success INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(recommendations)").fetchall()}
        for column, ddl in (
            ("sector", "ALTER TABLE recommendations ADD COLUMN sector TEXT"),
            ("max_gain_pct", "ALTER TABLE recommendations ADD COLUMN max_gain_pct REAL"),
            ("max_drawdown_pct", "ALTER TABLE recommendations ADD COLUMN max_drawdown_pct REAL"),
        ):
            if column not in existing_columns:
                conn.execute(ddl)

        for tag in DEFAULT_TAGS:
            conn.execute("INSERT OR IGNORE INTO strategy_weights (tag, weight) VALUES (?, 1.0)", (tag,))

        conn.execute(
            "INSERT OR IGNORE INTO watchlists (name, tickers, updated_at) VALUES ('default', ?, ?)",
            (
                json.dumps(
                    ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "TSM", "META", "AMZN",
                     "GOOGL", "TSLA", "ORCL", "PLTR", "AVGO", "CRM", "CRWV", "IBIT"]
                ),
                _utcnow(),
            ),
        )


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_account_balance() -> Optional[float]:
    raw = get_setting("account_balance")
    return float(raw) if raw is not None else None


def set_account_balance(balance: float) -> None:
    set_setting("account_balance", str(balance))


def get_risk_pct() -> Optional[float]:
    raw = get_setting("risk_pct")
    return float(raw) if raw is not None else None


def set_risk_pct(pct: float) -> None:
    set_setting("risk_pct", str(pct))


def log_api_call(provider: str, capability: str, symbol: Optional[str], success: bool) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO api_logs (created_at, provider, capability, symbol, success) VALUES (?, ?, ?, ?, ?)",
            (_utcnow(), provider, capability, symbol, 1 if success else 0),
        )


def get_weights() -> dict[str, float]:
    with _connect() as conn:
        rows = conn.execute("SELECT tag, weight FROM strategy_weights").fetchall()
        return {row["tag"]: row["weight"] for row in rows}


def record_recommendation(
    *, ticker: str, option_type: str, strike: float, expiration: str, entry_premium: float,
    take_profit_1: float, take_profit_2: float, stop_loss: float, confidence: float,
    risk_rating: str, strategy_tags: list[str], source: str = "manual", sector: Optional[str] = None,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO recommendations (
                created_at, ticker, option_type, strike, expiration, entry_premium,
                take_profit_1, take_profit_2, stop_loss, confidence, risk_rating,
                strategy_tags, source, sector
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utcnow(), ticker, option_type, strike, expiration, entry_premium,
                take_profit_1, take_profit_2, stop_loss, confidence, risk_rating,
                json.dumps(strategy_tags), source, sector,
            ),
        )
        return int(cur.lastrowid)


def get_open_recommendations() -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute("SELECT * FROM recommendations WHERE status = 'OPEN'").fetchall()


def close_recommendation(
    rec_id: int, *, status: str, exit_premium: float, return_pct: float,
    max_gain_pct: Optional[float] = None, max_drawdown_pct: Optional[float] = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE recommendations
            SET status = ?, exit_premium = ?, return_pct = ?, closed_at = ?,
                max_gain_pct = ?, max_drawdown_pct = ?
            WHERE id = ?
            """,
            (status, exit_premium, return_pct, _utcnow(), max_gain_pct, max_drawdown_pct, rec_id),
        )


def apply_learning(strategy_tags: list[str], *, won: bool) -> None:
    multiplier = WIN_MULTIPLIER if won else LOSS_MULTIPLIER
    with _connect() as conn:
        for tag in strategy_tags:
            row = conn.execute("SELECT weight, wins, losses FROM strategy_weights WHERE tag = ?", (tag,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO strategy_weights (tag, weight, wins, losses) VALUES (?, 1.0, 0, 0)", (tag,))
                weight, wins, losses = 1.0, 0, 0
            else:
                weight, wins, losses = row["weight"], row["wins"], row["losses"]
            new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, weight * multiplier))
            wins += 1 if won else 0
            losses += 0 if won else 1
            conn.execute(
                "UPDATE strategy_weights SET weight = ?, wins = ?, losses = ? WHERE tag = ?",
                (new_weight, wins, losses, tag),
            )


def record_backtest(
    *, ticker: str, strategy_tag: str, period: str, total_trades: int, win_rate: Optional[float],
    avg_return_pct: Optional[float], avg_hold_days: Optional[float], max_drawdown_pct: Optional[float],
    max_gain_pct: Optional[float], sharpe_ratio: Optional[float], sortino_ratio: Optional[float],
    profit_factor: Optional[float], expectancy: Optional[float], methodology_note: str,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO backtests (
                created_at, ticker, strategy_tag, period, total_trades, win_rate, avg_return_pct,
                avg_hold_days, max_drawdown_pct, max_gain_pct, sharpe_ratio, sortino_ratio,
                profit_factor, expectancy, methodology_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utcnow(), ticker, strategy_tag, period, total_trades, win_rate, avg_return_pct,
                avg_hold_days, max_drawdown_pct, max_gain_pct, sharpe_ratio, sortino_ratio,
                profit_factor, expectancy, methodology_note,
            ),
        )
        return int(cur.lastrowid)


def get_latest_backtest(ticker: str) -> Optional[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM backtests WHERE ticker = ? ORDER BY id DESC LIMIT 1", (ticker,)
        ).fetchone()


def record_alert(*, ticker: str, recommendation_id: int, confidence: float, channel: str, message: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO alerts (created_at, ticker, recommendation_id, confidence, channel, message) VALUES (?, ?, ?, ?, ?, ?)",
            (_utcnow(), ticker, recommendation_id, confidence, channel, message),
        )


def get_recent_alerts(limit: int = 10) -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def get_watchlist(name: str = "default") -> list[str]:
    with _connect() as conn:
        row = conn.execute("SELECT tickers FROM watchlists WHERE name = ?", (name,)).fetchone()
        return json.loads(row["tickers"]) if row else []


@dataclass
class Stats:
    total_trades: int
    wins: int
    losses: int
    open_trades: int
    win_rate: float
    avg_return_pct: float
    profit_factor: Optional[float]


def _closed_rows(conn: sqlite3.Connection, since: Optional[str] = None) -> list[sqlite3.Row]:
    if since:
        return conn.execute(
            "SELECT * FROM recommendations WHERE status != 'OPEN' AND closed_at >= ?", (since,)
        ).fetchall()
    return conn.execute("SELECT * FROM recommendations WHERE status != 'OPEN'").fetchall()


def get_overall_stats(since: Optional[str] = None) -> Stats:
    with _connect() as conn:
        closed = _closed_rows(conn, since)
        open_count = conn.execute("SELECT COUNT(*) AS c FROM recommendations WHERE status = 'OPEN'").fetchone()["c"]

    total = len(closed)
    wins = sum(1 for r in closed if r["status"].startswith("WIN"))
    losses = total - wins
    win_rate = round((wins / total) * 100, 1) if total else 0.0
    avg_return = round(sum(r["return_pct"] or 0 for r in closed) / total, 2) if total else 0.0

    gains = sum(r["return_pct"] for r in closed if (r["return_pct"] or 0) > 0)
    drawdowns = -sum(r["return_pct"] for r in closed if (r["return_pct"] or 0) < 0)
    profit_factor = round(gains / drawdowns, 2) if drawdowns > 0 else None

    return Stats(
        total_trades=total, wins=wins, losses=losses, open_trades=open_count,
        win_rate=win_rate, avg_return_pct=avg_return, profit_factor=profit_factor,
    )


def get_accuracy_by_ticker() -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT ticker, COUNT(*) AS total,
                   SUM(CASE WHEN status LIKE 'WIN%' THEN 1 ELSE 0 END) AS wins,
                   ROUND(AVG(return_pct), 2) AS avg_return
            FROM recommendations WHERE status != 'OPEN'
            GROUP BY ticker ORDER BY wins DESC, total DESC
            """
        ).fetchall()


def get_accuracy_by_sector() -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT COALESCE(sector, 'Unknown') AS sector, COUNT(*) AS total,
                   SUM(CASE WHEN status LIKE 'WIN%' THEN 1 ELSE 0 END) AS wins,
                   ROUND(AVG(return_pct), 2) AS avg_return
            FROM recommendations WHERE status != 'OPEN'
            GROUP BY sector ORDER BY wins DESC, total DESC
            """
        ).fetchall()


def get_accuracy_by_strategy() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT strategy_tags, status, return_pct FROM recommendations WHERE status != 'OPEN'").fetchall()

    tag_stats: dict[str, dict] = {}
    for row in rows:
        tags = json.loads(row["strategy_tags"])
        won = row["status"].startswith("WIN")
        for tag in tags:
            bucket = tag_stats.setdefault(tag, {"wins": 0, "total": 0, "return_sum": 0.0})
            bucket["total"] += 1
            bucket["wins"] += 1 if won else 0
            bucket["return_sum"] += row["return_pct"] or 0

    leaderboard = []
    for tag, bucket in tag_stats.items():
        win_rate = round((bucket["wins"] / bucket["total"]) * 100, 1) if bucket["total"] else 0.0
        avg_return = round(bucket["return_sum"] / bucket["total"], 2) if bucket["total"] else 0.0
        leaderboard.append({"tag": tag, "total": bucket["total"], "win_rate": win_rate, "avg_return": avg_return})
    leaderboard.sort(key=lambda x: (x["win_rate"], x["total"]), reverse=True)
    return leaderboard


def get_history(limit: int = 10, ticker: Optional[str] = None) -> list[sqlite3.Row]:
    with _connect() as conn:
        if ticker:
            return conn.execute(
                "SELECT * FROM recommendations WHERE ticker = ? ORDER BY id DESC LIMIT ?", (ticker, limit)
            ).fetchall()
        return conn.execute("SELECT * FROM recommendations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


init_db()
