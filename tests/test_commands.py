from price_alert_bot.commands import changes, interval_text, money

from .conftest import URL, URL2, product_page

CHAT = 42


# --------------------------------------------------------------- texts

def test_start_and_help(service):
    text = service.start("Max")
    assert "Hi Max!" in text
    for cmd in ("/track", "/list", "/remove", "/check", "/help"):
        assert cmd in text
    assert "every hour" in service.help()


def test_start_escapes_name(service):
    assert "&lt;b&gt;" in service.start("<b>")


def test_interval_and_money():
    assert interval_text(60) == "hour"
    assert interval_text(180) == "3 hours"
    assert interval_text(15) == "15 minutes"
    assert money(5) == "£5.00"
    assert money(None) == "unknown"


# --------------------------------------------------------------- /track

def test_track(service, storage):
    reply = service.track(CHAT, [URL])
    assert "Now watching #1" in reply
    assert "A Light in the Attic" in reply
    assert "£51.77" in reply
    assert storage.count_for_chat(CHAT) == 1


def test_track_without_link(service):
    assert "Please send a link" in service.track(CHAT, [])


def test_track_with_target(service, storage):
    reply = service.track(CHAT, [URL, "45"])
    assert "Target price: £45.00" in reply
    assert "already" not in reply
    assert storage.get_by_url(CHAT, URL).target_price == 45


def test_track_target_already_reached(service, storage):
    reply = service.track(CHAT, [URL, "60"])
    assert "already at or below your target" in reply
    assert storage.get_by_url(CHAT, URL).target_hit is True


def test_track_bad_target(service, storage):
    assert "not a valid target price" in service.track(CHAT, [URL, "cheap"])
    assert "not a valid target price" in service.track(CHAT, [URL, "0"])
    assert storage.count_for_chat(CHAT) == 0


def test_track_wrong_shop(service, shop):
    reply = service.track(CHAT, ["https://www.amazon.de/dp/123"])
    assert "only track products from" in reply
    assert shop.requested == []  # never downloaded


def test_track_unreachable_page(service, shop, storage):
    shop.fail.add(URL)
    assert "could not load" in service.track(CHAT, [URL])
    assert storage.count_for_chat(CHAT) == 0


def test_track_same_link_again_updates(service, storage):
    service.track(CHAT, [URL])
    reply = service.track(CHAT, [URL, "40"])
    assert "Updated #1" in reply
    assert storage.count_for_chat(CHAT) == 1


def test_track_limit(service, shop, storage):
    for n in range(3):  # max_items_per_chat=3 in conftest
        url = f"https://books.toscrape.com/catalogue/book_{n}/index.html"
        shop.pages[url] = product_page(title=f"Book {n}")
        service.track(CHAT, [url])
    reply = service.track(CHAT, [URL])
    assert "already watching 3 products" in reply
    assert storage.count_for_chat(CHAT) == 3
    # updating an existing item is still allowed at the limit
    assert "Updated" in service.track(CHAT, ["https://books.toscrape.com/catalogue/book_0/index.html", "10"])


def test_html_in_titles_is_escaped(service, shop):
    shop.pages[URL] = product_page(title="Tom & Jerry <3")
    assert "Tom &amp; Jerry &lt;3" in service.track(CHAT, [URL])


# ---------------------------------------------------------- /list /remove

def test_list_empty(service):
    assert "not watching anything" in service.list_items(CHAT)


def test_list(service):
    service.track(CHAT, [URL, "45"])
    text = service.list_items(CHAT)
    assert "Your watchlist (1)" in text
    assert "#1" in text
    assert "£51.77, in stock, target £45.00" in text


def test_remove(service, storage):
    service.track(CHAT, [URL])
    assert "Stopped watching" in service.remove(CHAT, ["#1"])
    assert storage.count_for_chat(CHAT) == 0


def test_remove_bad_input(service):
    assert "Which one?" in service.remove(CHAT, [])
    assert "Which one?" in service.remove(CHAT, ["abc"])
    assert "could not find" in service.remove(CHAT, ["99"])


def test_cannot_remove_other_chats_item(service, storage):
    service.track(CHAT, [URL])
    assert "could not find" in service.remove(7, ["1"])
    assert storage.count_for_chat(CHAT) == 1


# ------------------------------------------------------- change detection

def _item(storage, price=51.77, in_stock=True, target=None, hit=False):
    item = storage.add(CHAT, URL, "Book", price, in_stock, target)
    if hit:
        storage.update_check(item.id, price, in_stock, True)
    return storage.get_by_url(CHAT, URL)


def test_no_change(storage):
    assert changes(_item(storage), 51.77, True) == ([], False)


def test_price_drop_and_rise(storage):
    notes, _ = changes(_item(storage), 40.0, True)
    assert notes == ["📉 Price dropped: £51.77 → <b>£40.00</b>"]
    notes, _ = changes(_item(storage), 60.0, True)
    assert notes[0].startswith("📈 Price went up")


def test_stock_changes(storage):
    assert changes(_item(storage, in_stock=False), 51.77, True)[0] == ["✅ Back in stock!"]
    assert changes(_item(storage, in_stock=True), 51.77, False)[0] == ["❌ Now out of stock"]


def test_target_reached_only_once(storage):
    notes, hit = changes(_item(storage, target=45), 44.0, True)
    assert any("Target price £45.00 reached" in n for n in notes)
    assert hit is True
    notes, hit = changes(_item(storage, price=44.0, target=45, hit=True), 44.0, True)
    assert notes == [] and hit is True


def test_target_rearms_when_price_goes_up(storage):
    _, hit = changes(_item(storage, price=44.0, target=45, hit=True), 50.0, True)
    assert hit is False


def test_unknown_price_changes_nothing(storage):
    assert changes(_item(storage, target=45), None, True) == ([], False)


# ------------------------------------------------------ scheduled checks

def test_check_all_sends_alert_and_saves(service, shop, storage):
    service.track(CHAT, [URL, "45"])
    shop.pages[URL] = product_page(price="£44.00")
    alerts = service.check_all()
    assert len(alerts) == 1
    assert alerts[0].chat_id == CHAT
    assert "Price dropped" in alerts[0].text and "Target price" in alerts[0].text
    item = storage.get_by_url(CHAT, URL)
    assert item.last_price == 44.0 and item.target_hit is True
    assert service.check_all() == []  # same price again: no repeated alert


def test_check_all_downloads_each_url_once(service, shop):
    service.track(1, [URL])
    service.track(2, [URL])
    shop.requested.clear()
    shop.pages[URL] = product_page(price="£10.00")
    alerts = service.check_all()
    assert shop.requested == [URL]
    assert {a.chat_id for a in alerts} == {1, 2}


def test_check_all_skips_failing_pages(service, shop, storage):
    shop.pages[URL2] = product_page(title="Tipping the Velvet")
    service.track(CHAT, [URL])
    service.track(CHAT, [URL2])
    shop.fail.add(URL)
    shop.pages[URL2] = product_page(price="£1.00", title="Tipping the Velvet")
    alerts = service.check_all()
    assert len(alerts) == 1 and "Tipping the Velvet" in alerts[0].text
    assert storage.get_by_url(CHAT, URL).last_price == 51.77  # old value kept


def test_check_command(service, shop):
    assert "Nothing to check" in service.check_chat(CHAT)
    service.track(CHAT, [URL])
    assert "no changes" in service.check_chat(CHAT)
    shop.pages[URL] = product_page(stock="Out of stock")
    assert "out of stock" in service.check_chat(CHAT)


def test_check_command_only_checks_own_chat(service, shop):
    shop.pages[URL2] = product_page(title="Other")
    service.track(CHAT, [URL])
    service.track(7, [URL2])
    shop.requested.clear()
    service.check_chat(CHAT)
    assert shop.requested == [URL]
