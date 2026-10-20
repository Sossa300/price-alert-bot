import pytest

from price_alert_bot.prices import (
    ProductError,
    ProductFetcher,
    check_url,
    parse_price,
    parse_product,
    parse_stock,
)

from .conftest import BOOK_HTML, URL, FakeShop, product_page


@pytest.mark.parametrize("text, expected", [
    ("£51.77", 51.77),
    ("55", 55.0),
    ("55,5", 55.5),
    ("£ 1299.00", 1299.0),
    ("abc", None),
    ("", None),
    (None, None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("In stock (22 available)", (True, 22)),
    ("In stock", (True, None)),
    ("Out of stock", (False, 0)),
    (None, (None, None)),
])
def test_parse_stock(text, expected):
    assert parse_stock(text) == expected


def test_parse_product():
    p = parse_product(BOOK_HTML, URL)
    assert p.title == "A Light in the Attic"
    assert p.price == 51.77
    assert p.in_stock is True
    assert p.stock_count == 22
    assert p.url == URL


def test_parse_product_out_of_stock():
    p = parse_product(product_page(stock="Out of stock"), URL)
    assert p.in_stock is False
    assert p.stock_count == 0


def test_parse_non_product_page():
    with pytest.raises(ProductError, match="not a product page"):
        parse_product("<html><body><h1>Home</h1></body></html>", URL)


@pytest.mark.parametrize("url", [
    URL,
    f"  <{URL}> ",
    "https://www.books.toscrape.com/catalogue/x/index.html",
])
def test_check_url_accepts(url):
    assert check_url(url).startswith("https://")


@pytest.mark.parametrize("url, message", [
    ("hello", "does not look like a link"),
    ("ftp://books.toscrape.com/x", "does not look like a link"),
    ("https://www.amazon.de/dp/123", "only track products from"),
])
def test_check_url_rejects(url, message):
    with pytest.raises(ProductError, match=message):
        check_url(url)


def test_fetcher_uses_source():
    shop = FakeShop()
    product = ProductFetcher(shop).fetch(URL)
    assert product.price == 51.77
    assert shop.requested == [URL]


def test_fetcher_turns_network_errors_into_product_error():
    shop = FakeShop()
    shop.fail.add(URL)
    with pytest.raises(ProductError, match="could not load"):
        ProductFetcher(shop).fetch(URL)


def test_fetcher_404():
    with pytest.raises(ProductError):
        ProductFetcher(FakeShop({})).fetch(URL)
