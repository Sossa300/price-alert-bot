"""Fetch a product page and read title, price and stock from it.

The network part (PoliteSession) comes from book_scraper. This module adds
the "product page -> Product" step. For a client's shop you change
ALLOWED_HOSTS and parse_product(), everything else stays the same.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from book_scraper.fetcher import PoliteSession
from book_scraper.parser import parse_book_detail
from book_scraper.scraper import FETCH_ERRORS, HtmlSource

log = logging.getLogger(__name__)

# Only shops whose pages parse_product() understands.
ALLOWED_HOSTS = {"books.toscrape.com"}
CURRENCY = "£"
USER_AGENT = "price-alert-bot/1.0 (+https://github.com/Sossa300/price-alert-bot)"


class ProductError(Exception):
    """A user-facing problem: bad URL, page not reachable, page not a product."""


@dataclass
class Product:
    url: str
    title: str
    price: float | None
    in_stock: bool | None
    stock_count: int | None = None


def parse_price(text: str | None) -> float | None:
    """'£51.77' -> 51.77, '55,5' -> 55.5, 'abc' or None -> None."""
    if not text:
        return None
    number = re.sub(r"[^\d.]", "", text.replace(",", "."))
    try:
        return float(number)
    except ValueError:
        return None


def parse_stock(text: str | None) -> tuple[bool | None, int | None]:
    """'In stock (22 available)' -> (True, 22), 'Out of stock' -> (False, 0)."""
    if not text:
        return None, None
    if "out of stock" in text.lower():
        return False, 0
    match = re.search(r"(\d+)\s+available", text)
    count = int(match.group(1)) if match else None
    return ("in stock" in text.lower()) or None, count


def check_url(url: str) -> str:
    """Return the cleaned URL or raise ProductError with a helpful message."""
    url = url.strip().strip("<>")
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ProductError("That does not look like a link. It should start with https://")
    host = parts.netloc.lower().removeprefix("www.")
    if host not in ALLOWED_HOSTS:
        raise ProductError(
            f"Sorry, I can only track products from: {', '.join(sorted(ALLOWED_HOSTS))}"
        )
    return url


def parse_product(html: str, url: str) -> Product:
    """Read a books.toscrape.com product page."""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.select_one("div.product_main h1")
    price_tag = soup.select_one("div.product_main p.price_color")
    if title_tag is None or price_tag is None:
        raise ProductError("This page is not a product page (no title or price found).")

    in_stock, count = parse_stock(parse_book_detail(html).get("stock"))
    return Product(
        url=url,
        title=title_tag.get_text(strip=True),
        price=parse_price(price_tag.get_text(strip=True)),
        in_stock=in_stock,
        stock_count=count,
    )


class ProductFetcher:
    """Downloads and parses product pages.

    `source` is anything with get_html(url). The bot passes a PoliteSession,
    the tests pass a fake that returns saved HTML, so no internet is needed.
    """

    def __init__(self, source: HtmlSource) -> None:
        self.source = source

    def fetch(self, url: str) -> Product:
        url = check_url(url)
        try:
            html = self.source.get_html(url)
        except FETCH_ERRORS as exc:
            log.warning("Could not load %s: %s", url, exc)
            raise ProductError("I could not load that page. Please check the link.") from exc
        return parse_product(html, url)


def build_fetcher(delay: float = 1.0) -> ProductFetcher:
    return ProductFetcher(PoliteSession(delay=delay, user_agent=USER_AGENT))
