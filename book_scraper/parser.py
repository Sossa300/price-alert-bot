"""Turn the HTML of books.toscrape.com into plain Python dictionaries.

This is the ONLY file that knows how the website looks. Every CSS selector
lives here. If you adapt the scraper to another site (a client's shop, a
job board ...), this is the file you rewrite, the rest can stay.

Tip: open the page in your browser, right-click an element -> "Inspect" and
look for class names you can use with soup.select(...).

The functions return raw text ("£51.77", "Three"). Turning that into numbers
is the job of cleaning.py, so parsing and cleaning can be tested separately.
"""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _text(tag: Tag | None) -> str | None:
    """Return the stripped text of a tag, or None if the tag is missing."""
    return tag.get_text(strip=True) if tag else None


def parse_listing(html: str, page_url: str) -> list[dict]:
    """Extract all books from a catalogue or category page.

    page_url is needed to turn relative links ("a-light_1000/index.html")
    into absolute ones ("https://books.toscrape.com/catalogue/a-light_1000/...").
    """
    books = []
    for pod in _soup(html).select("article.product_pod"):
        link = pod.select_one("h3 a")
        image = pod.select_one("img")
        rating = pod.select_one("p.star-rating")
        books.append({
            # The visible link text is shortened ("A Light in the ..."),
            # the full title is in the title attribute.
            "title": link.get("title") or _text(link),
            "price": _text(pod.select_one("p.price_color")),
            # <p class="star-rating Three"> -> "Three"
            "rating": next((c for c in rating.get("class", []) if c != "star-rating"), None)
                      if rating else None,
            "availability": _text(pod.select_one("p.availability")),
            "url": urljoin(page_url, link["href"]),
            "image_url": urljoin(page_url, image["src"]) if image else None,
        })
    return books


def next_page_url(html: str, page_url: str) -> str | None:
    """Return the absolute URL of the "next" page, or None on the last page."""
    link = _soup(html).select_one("ul.pager li.next a")
    return urljoin(page_url, link["href"]) if link else None


def parse_categories(html: str, page_url: str) -> dict[str, str]:
    """Return {category name: absolute URL} from the sidebar of any page."""
    links = _soup(html).select("div.side_categories ul li ul li a")
    return {a.get_text(strip=True): urljoin(page_url, a["href"]) for a in links}


def parse_book_detail(html: str) -> dict:
    """Extract the extra fields that only exist on a book's own page."""
    soup = _soup(html)

    # The product table: <tr><th>UPC</th><td>a897fe...</td></tr>
    table = {
        _text(row.th): _text(row.td)
        for row in soup.select("table.table-striped tr")
        if row.th and row.td
    }
    # Breadcrumb: Home > Books > Poetry > Title. The category is the last link.
    crumbs = soup.select("ul.breadcrumb li a")

    return {
        "category": _text(crumbs[-1]) if len(crumbs) >= 3 else None,
        "upc": table.get("UPC"),
        "stock": table.get("Availability"),  # "In stock (22 available)"
        "num_reviews": table.get("Number of reviews"),
        "description": _text(soup.select_one("#product_description ~ p")),
    }
