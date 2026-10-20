"""The crawl loop: fetch a page, parse it, follow the "next" link, repeat.

`session` can be anything with a get_html(url) method. In real runs that is
a PoliteSession, in tests a fake that returns saved HTML files. This trick
("dependency injection") is why the tests need no internet.
"""

from __future__ import annotations

import logging
from typing import Callable, Protocol

import requests

from .fetcher import RobotsDisallowed
from .parser import next_page_url, parse_book_detail, parse_categories, parse_listing

log = logging.getLogger(__name__)

BASE_URL = "https://books.toscrape.com/"
CATALOGUE_URL = BASE_URL + "catalogue/page-1.html"

# Errors that should stop or skip a page, but never crash the whole run.
FETCH_ERRORS = (requests.RequestException, RobotsDisallowed)


class HtmlSource(Protocol):
    def get_html(self, url: str) -> str: ...


def list_categories(session: HtmlSource, home_url: str = BASE_URL) -> dict[str, str]:
    """Return {category name: URL} as shown in the website's sidebar."""
    return parse_categories(session.get_html(home_url), home_url)


def find_category_url(session: HtmlSource, name: str, home_url: str = BASE_URL) -> str:
    """Look up a category by name, case-insensitive ("travel" -> Travel URL)."""
    categories = list_categories(session, home_url)
    for label, url in categories.items():
        if label.lower() == name.strip().lower():
            return url
    raise ValueError(
        f"Unknown category {name!r}. Available: {', '.join(sorted(categories))}"
    )


def scrape_books(
    session: HtmlSource,
    start_url: str = CATALOGUE_URL,
    max_pages: int | None = None,
    details: bool = False,
    on_page: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Scrape listing pages starting at start_url.

    max_pages: stop after this many pages (None = until the last page).
    details:   also open every book's own page for category, UPC and stock.
    on_page:   optional callback(page_number, books_so_far), e.g. for a progress bar.

    If a page fails after all retries, the books collected so far are
    returned instead of losing everything.
    """
    records: list[dict] = []
    url: str | None = start_url
    page = 0

    while url and (max_pages is None or page < max_pages):
        page += 1
        try:
            html = session.get_html(url)
        except FETCH_ERRORS as exc:
            log.error("Stopping at page %d, could not load %s: %s", page, url, exc)
            break

        books = parse_listing(html, url)
        log.info("Page %d: %d books (%s)", page, len(books), url)

        if details:
            for book in books:
                try:
                    book.update(parse_book_detail(session.get_html(book["url"])))
                except FETCH_ERRORS as exc:
                    log.warning("Skipping details for %s: %s", book["url"], exc)

        records.extend(books)
        if on_page:
            on_page(page, len(records))
        url = next_page_url(html, url)

    log.info("Finished: %d books from %d page(s)", len(records), page)
    return records
