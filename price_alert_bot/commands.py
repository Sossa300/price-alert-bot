"""What the bot does, without any Telegram code.

Every command is a plain method that takes a chat id and the words after the
command, and returns the reply text. That has two big advantages:

1. Tests can call these methods directly, no Telegram, no token, no internet.
2. Moving to Discord (or Slack, or a web form) means rewriting only bot.py.

Replies use Telegram's HTML formatting (<b>, <i>, <a>), so every value that
comes from a website or a user goes through html.escape() first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape

from .prices import CURRENCY, ProductError, ProductFetcher, check_url, parse_price
from .storage import Item, Storage

log = logging.getLogger(__name__)

HELP_TEXT = """<b>Commands</b>
/track &lt;link&gt; [target] - watch a product, optionally with a target price
/list - show everything you are watching
/remove &lt;number&gt; - stop watching a product (number from /list)
/check - check your products right now
/help - show this message

<b>Example</b>
<code>/track https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html 50</code>

I check all products automatically every {interval} and message you when \
a price changes, a product is back in stock, or your target price is reached."""


@dataclass
class Alert:
    """A message the scheduled check wants to send to a chat."""
    chat_id: int
    text: str


def money(value: float | None) -> str:
    return "unknown" if value is None else f"{CURRENCY}{value:.2f}"


def stock_text(in_stock: bool | None) -> str:
    return {True: "in stock", False: "out of stock"}.get(in_stock, "stock unknown")


def interval_text(minutes: float) -> str:
    if minutes >= 60 and minutes % 60 == 0:
        hours = int(minutes // 60)
        return "hour" if hours == 1 else f"{hours} hours"
    return f"{minutes:g} minutes"


def link(item_or_url: str, title: str) -> str:
    return f'<a href="{escape(item_or_url)}">{escape(title)}</a>'


def changes(item: Item, price: float | None, in_stock: bool | None) -> tuple[list[str], bool]:
    """Compare a stored item with fresh values.

    Returns (list of change messages, new target_hit flag). This is pure
    logic, so the rules for when to notify are easy to test and to adapt.
    """
    notes: list[str] = []
    old = item.last_price

    if price is not None and old is not None and price != old:
        arrow = "📉 Price dropped" if price < old else "📈 Price went up"
        notes.append(f"{arrow}: {money(old)} → <b>{money(price)}</b>")

    if item.in_stock is False and in_stock is True:
        notes.append("✅ Back in stock!")
    elif item.in_stock is True and in_stock is False:
        notes.append("❌ Now out of stock")

    target_hit = item.target_hit
    if item.target_price is not None and price is not None:
        if price <= item.target_price and not item.target_hit:
            notes.append(f"🎯 Target price {money(item.target_price)} reached: <b>{money(price)}</b>")
            target_hit = True
        elif price > item.target_price:
            target_hit = False  # arm the alert again for the next drop

    return notes, target_hit


class BotService:
    def __init__(self, storage: Storage, fetcher: ProductFetcher,
                 max_items_per_chat: int = 20, check_interval_minutes: float = 60) -> None:
        self.storage = storage
        self.fetcher = fetcher
        self.max_items = max_items_per_chat
        self.interval = check_interval_minutes

    # ------------------------------------------------------------ commands

    def start(self, first_name: str | None = None) -> str:
        hello = f"Hi {escape(first_name)}! " if first_name else "Hi! "
        return (
            f"👋 {hello}I watch product prices for you and send a message "
            "when something changes.\n\n" + self.help()
        )

    def help(self) -> str:
        return HELP_TEXT.format(interval=interval_text(self.interval))

    def track(self, chat_id: int, args: list[str]) -> str:
        if not args:
            return "Please send a link: <code>/track &lt;link&gt; [target price]</code>"

        target = None
        if len(args) > 1:
            target = parse_price(args[1])
            if target is None or target <= 0:
                return f"“{escape(args[1])}” is not a valid target price. Example: <code>45.50</code>"

        try:
            url = check_url(args[0])
            existing = self.storage.get_by_url(chat_id, url)
            if existing is None and self.storage.count_for_chat(chat_id) >= self.max_items:
                return f"You are already watching {self.max_items} products. Remove one with /remove first."
            product = self.fetcher.fetch(url)
        except ProductError as exc:
            return f"⚠️ {escape(str(exc))}"

        item = self.storage.add(chat_id, product.url, product.title,
                                product.price, product.in_stock, target)
        verb = "Updated" if existing else "Now watching"
        lines = [
            f"✅ {verb} #{item.id}: {link(product.url, product.title)}",
            f"Price: <b>{money(product.price)}</b> ({stock_text(product.in_stock)})",
        ]
        if target is not None:
            lines.append(f"Target price: {money(target)}")
            if product.price is not None and product.price <= target:
                lines.append("🎯 The price is already at or below your target!")
                self.storage.update_check(item.id, product.price, product.in_stock, True)
        return "\n".join(lines)

    def list_items(self, chat_id: int) -> str:
        items = self.storage.list_for_chat(chat_id)
        if not items:
            return "You are not watching anything yet. Start with /track &lt;link&gt;"
        lines = [f"<b>Your watchlist ({len(items)})</b>"]
        for item in items:
            line = f"\n#{item.id} {link(item.url, item.title)}\n    {money(item.last_price)}, {stock_text(item.in_stock)}"
            if item.target_price is not None:
                line += f", target {money(item.target_price)}"
            lines.append(line)
        lines.append("\nStop watching one with <code>/remove &lt;number&gt;</code>")
        return "\n".join(lines)

    def remove(self, chat_id: int, args: list[str]) -> str:
        if not args or not args[0].lstrip("#").isdigit():
            return "Which one? Send the number from /list, e.g. <code>/remove 3</code>"
        item = self.storage.remove(chat_id, int(args[0].lstrip("#")))
        if item is None:
            return "I could not find that number in your list. See /list"
        return f"🗑 Stopped watching {link(item.url, item.title)}"

    def check_chat(self, chat_id: int) -> str:
        """The /check command: check this chat's items now and report."""
        items = self.storage.list_for_chat(chat_id)
        if not items:
            return "Nothing to check yet. Start with /track &lt;link&gt;"
        alerts = self._check(items)
        if not alerts:
            return f"🔍 Checked {len(items)} product(s): no changes."
        return "\n\n".join(a.text for a in alerts)

    # ------------------------------------------------------ scheduled job

    def check_all(self) -> list[Alert]:
        """Check every tracked item of every chat (called by the scheduler)."""
        return self._check(self.storage.all_items())

    def _check(self, items: list[Item]) -> list[Alert]:
        alerts: list[Alert] = []
        cache: dict[str, object] = {}  # download each URL only once per run
        for item in items:
            if item.url not in cache:
                try:
                    cache[item.url] = self.fetcher.fetch(item.url)
                except ProductError as exc:
                    log.warning("Check failed for %s: %s", item.url, exc)
                    cache[item.url] = None
            product = cache[item.url]
            if product is None:
                continue  # try again next time, keep the old values

            notes, target_hit = changes(item, product.price, product.in_stock)
            self.storage.update_check(item.id, product.price, product.in_stock, target_hit)
            if notes:
                alerts.append(Alert(item.chat_id, f"{link(item.url, item.title)}\n" + "\n".join(notes)))
        log.info("Checked %d item(s), %d alert(s)", len(items), len(alerts))
        return alerts
