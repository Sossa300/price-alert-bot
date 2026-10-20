"""Shared test helpers.

No test talks to Telegram or the internet. Product pages come from a saved
HTML file, and the "shop" is a fake whose prices the tests can change.
"""

from pathlib import Path

import pytest
import requests

from price_alert_bot.commands import BotService
from price_alert_bot.prices import ProductFetcher
from price_alert_bot.storage import Storage

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
URL2 = "https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html"

BOOK_HTML = (FIXTURES / "book_detail.html").read_text(encoding="utf-8")


def product_page(price: str = "£51.77", stock: str = "In stock (22 available)",
                 title: str = "A Light in the Attic") -> str:
    """The saved product page with a different price, stock text or title."""
    return (BOOK_HTML.replace("£51.77", price)
                     .replace("In stock (22 available)", stock)
                     .replace("A Light in the Attic", title))


class FakeShop:
    """Stands in for PoliteSession: serves pages from a dict, can simulate errors."""

    def __init__(self, pages: dict[str, str] | None = None):
        self.pages = pages if pages is not None else {URL: product_page()}
        self.fail: set[str] = set()
        self.requested: list[str] = []

    def get_html(self, url: str) -> str:
        self.requested.append(url)
        if url in self.fail:
            raise requests.ConnectionError("simulated network error")
        if url not in self.pages:
            raise requests.HTTPError(f"404 for {url}")
        return self.pages[url]


@pytest.fixture
def shop():
    return FakeShop()


@pytest.fixture
def storage():
    store = Storage(":memory:")
    yield store
    store.close()


@pytest.fixture
def service(storage, shop):
    return BotService(storage, ProductFetcher(shop), max_items_per_chat=3)
