"""SQLite storage for tracked products.

SQLite is a whole database in a single file, built into Python. No server,
no setup, and it survives restarts of the bot. For a client project with
many users you could swap this class for PostgreSQL without touching the
command logic, because commands.py only calls the methods below.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    url           TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    last_price    REAL,
    in_stock      INTEGER,
    target_price  REAL,
    target_hit    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    checked_at    TEXT,
    UNIQUE (chat_id, url)
);
"""


@dataclass
class Item:
    id: int
    chat_id: int
    url: str
    title: str
    last_price: float | None
    in_stock: bool | None
    target_price: float | None
    target_hit: bool
    created_at: str
    checked_at: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_item(row: sqlite3.Row) -> Item:
    data = dict(row)
    data["in_stock"] = None if data["in_stock"] is None else bool(data["in_stock"])
    data["target_hit"] = bool(data["target_hit"])
    return Item(**data)


class Storage:
    """All database access goes through this class."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the bot runs blocking work in a worker
        # thread. All writes are short and committed right away.
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def add(self, chat_id: int, url: str, title: str, price: float | None,
            in_stock: bool | None, target_price: float | None = None) -> Item:
        """Start tracking a URL. Tracking it again updates the target price."""
        with self.conn:  # commits on success, rolls back on error
            self.conn.execute(
                """INSERT INTO items (chat_id, url, title, last_price, in_stock,
                                      target_price, created_at, checked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (chat_id, url) DO UPDATE SET
                       title = excluded.title,
                       last_price = excluded.last_price,
                       in_stock = excluded.in_stock,
                       target_price = excluded.target_price,
                       target_hit = 0,
                       checked_at = excluded.checked_at""",
                (chat_id, url, title, price, in_stock, target_price, _now(), _now()),
            )
        return self.get_by_url(chat_id, url)

    def get_by_url(self, chat_id: int, url: str) -> Item | None:
        row = self.conn.execute(
            "SELECT * FROM items WHERE chat_id = ? AND url = ?", (chat_id, url)
        ).fetchone()
        return _to_item(row) if row else None

    def list_for_chat(self, chat_id: int) -> list[Item]:
        rows = self.conn.execute(
            "SELECT * FROM items WHERE chat_id = ? ORDER BY id", (chat_id,)
        ).fetchall()
        return [_to_item(r) for r in rows]

    def count_for_chat(self, chat_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM items WHERE chat_id = ?", (chat_id,)
        ).fetchone()[0]

    def all_items(self) -> list[Item]:
        rows = self.conn.execute("SELECT * FROM items ORDER BY id").fetchall()
        return [_to_item(r) for r in rows]

    def remove(self, chat_id: int, item_id: int) -> Item | None:
        """Delete one item. The chat_id check stops users deleting others' items."""
        rows = self.conn.execute(
            "SELECT * FROM items WHERE id = ? AND chat_id = ?", (item_id, chat_id)
        ).fetchone()
        if rows is None:
            return None
        with self.conn:
            self.conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        return _to_item(rows)

    def update_check(self, item_id: int, price: float | None, in_stock: bool | None,
                     target_hit: bool) -> None:
        """Save the result of a price check."""
        with self.conn:
            self.conn.execute(
                """UPDATE items SET last_price = ?, in_stock = ?, target_hit = ?,
                                    checked_at = ?
                   WHERE id = ?""",
                (price, in_stock, int(target_hit), _now(), item_id),
            )
