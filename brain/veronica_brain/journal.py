"""Дневник Veronica — SQLite. Снимки состояния, сделки, события, разборы."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    ts TEXT NOT NULL,
    equity REAL NOT NULL,          -- общий капитал (USDT) с учётом открытых позиций
    profit_closed REAL NOT NULL,   -- закрытая прибыль с начала
    profit_all REAL NOT NULL,      -- вся прибыль (вкл. открытые)
    open_trades INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    bot_state TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS snapshots_ts ON snapshots(ts);

CREATE TABLE IF NOT EXISTS trades (
    trade_id INTEGER PRIMARY KEY,  -- id сделки в freqtrade
    pair TEXT NOT NULL,
    strategy TEXT NOT NULL,
    enter_tag TEXT,
    exit_reason TEXT,
    open_date TEXT NOT NULL,
    close_date TEXT,
    open_rate REAL,
    close_rate REAL,
    stake_amount REAL,
    profit_abs REAL,
    profit_ratio REAL,
    duration_min INTEGER,
    raw TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,            -- halt / resume / switch / daily_loss / info / error
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    ts TEXT NOT NULL,
    strategy TEXT NOT NULL,
    verdict TEXT NOT NULL,         -- keep / tune / switch
    recommended TEXT,
    confidence REAL,
    summary TEXT NOT NULL,
    applied INTEGER NOT NULL DEFAULT 0,
    raw TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Journal:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- kv -----------------------------------------------------------------
    def get(self, key: str, default: str | None = None) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?, ?)", (key, value))

    def get_json(self, key: str, default: Any = None) -> Any:
        raw = self.get(key)
        return json.loads(raw) if raw is not None else default

    def set_json(self, key: str, value: Any) -> None:
        self.set(key, json.dumps(value, ensure_ascii=False))

    # --- snapshots ----------------------------------------------------------
    def add_snapshot(self, equity: float, profit_closed: float, profit_all: float,
                     open_trades: int, strategy: str, bot_state: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO snapshots VALUES (?,?,?,?,?,?,?)",
                (utcnow(), equity, profit_closed, profit_all, open_trades, strategy, bot_state),
            )

    def equity_curve(self, since_iso: str | None = None, limit: int = 2000) -> list[dict]:
        q = "SELECT ts, equity FROM snapshots"
        args: tuple = ()
        if since_iso:
            q += " WHERE ts >= ?"
            args = (since_iso,)
        q += " ORDER BY ts DESC LIMIT ?"
        with self._conn() as c:
            rows = c.execute(q, args + (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def peak_equity(self) -> float | None:
        with self._conn() as c:
            row = c.execute("SELECT MAX(equity) AS m FROM snapshots").fetchone()
            return row["m"] if row and row["m"] is not None else None

    # --- trades -------------------------------------------------------------
    def upsert_trade(self, t: dict) -> bool:
        """Возвращает True, если сделка новая (ещё не была в дневнике)."""
        with self._conn() as c:
            exists = c.execute("SELECT 1 FROM trades WHERE trade_id=?", (t["trade_id"],)).fetchone()
            c.execute(
                """INSERT OR REPLACE INTO trades
                   (trade_id, pair, strategy, enter_tag, exit_reason, open_date, close_date,
                    open_rate, close_rate, stake_amount, profit_abs, profit_ratio, duration_min, raw)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    t["trade_id"], t["pair"], t.get("strategy") or "?", t.get("enter_tag"),
                    t.get("exit_reason"), t["open_date"], t.get("close_date"),
                    t.get("open_rate"), t.get("close_rate"), t.get("stake_amount"),
                    t.get("profit_abs"), t.get("profit_ratio"), t.get("trade_duration"),
                    json.dumps(t, ensure_ascii=False),
                ),
            )
            return exists is None

    def trades_since(self, since_iso: str, strategy: str | None = None) -> list[dict]:
        q = "SELECT * FROM trades WHERE close_date >= ?"
        args: list = [since_iso]
        if strategy:
            q += " AND strategy = ?"
            args.append(strategy)
        q += " ORDER BY close_date"
        with self._conn() as c:
            return [dict(r) for r in c.execute(q, args).fetchall()]

    def trade_count(self, strategy: str | None = None) -> int:
        with self._conn() as c:
            if strategy:
                return c.execute("SELECT COUNT(*) FROM trades WHERE strategy=?", (strategy,)).fetchone()[0]
            return c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

    # --- events / reviews ---------------------------------------------------
    def add_event(self, kind: str, text: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO events VALUES (?,?,?)", (utcnow(), kind, text))

    def recent_events(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def add_review(self, strategy: str, verdict: str, recommended: str | None, confidence: float | None,
                   summary: str, applied: bool, raw: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?)",
                (utcnow(), strategy, verdict, recommended, confidence, summary, int(applied),
                 json.dumps(raw, ensure_ascii=False)),
            )

    def recent_reviews(self, limit: int = 7) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM reviews ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
