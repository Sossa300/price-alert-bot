from price_alert_bot.storage import Storage

from .conftest import URL, URL2


def test_add_and_list(storage):
    item = storage.add(1, URL, "Book", 51.77, True, 50.0)
    assert item.id == 1
    assert item.title == "Book"
    assert item.last_price == 51.77
    assert item.in_stock is True
    assert item.target_price == 50.0
    assert item.target_hit is False
    assert [i.url for i in storage.list_for_chat(1)] == [URL]


def test_chats_are_separate(storage):
    storage.add(1, URL, "Book", 10, True)
    storage.add(2, URL2, "Other", 20, True)
    assert [i.url for i in storage.list_for_chat(1)] == [URL]
    assert storage.count_for_chat(2) == 1
    assert len(storage.all_items()) == 2


def test_adding_same_url_twice_updates(storage):
    storage.add(1, URL, "Book", 10, True, 9)
    storage.update_check(1, 8, True, target_hit=True)
    item = storage.add(1, URL, "Book", 8, True, 7)
    assert storage.count_for_chat(1) == 1
    assert item.id == 1
    assert item.target_price == 7
    assert item.target_hit is False  # new target, alert armed again


def test_remove_only_own_items(storage):
    storage.add(1, URL, "Book", 10, True)
    assert storage.remove(2, 1) is None  # other chat cannot delete it
    assert storage.count_for_chat(1) == 1
    removed = storage.remove(1, 1)
    assert removed.title == "Book"
    assert storage.count_for_chat(1) == 0
    assert storage.remove(1, 1) is None


def test_update_check(storage):
    storage.add(1, URL, "Book", 10, True)
    storage.update_check(1, 9.5, False, target_hit=True)
    item = storage.get_by_url(1, URL)
    assert item.last_price == 9.5
    assert item.in_stock is False
    assert item.target_hit is True
    assert item.checked_at is not None


def test_unknown_values_stay_none(storage):
    item = storage.add(1, URL, "Book", None, None)
    assert item.last_price is None
    assert item.in_stock is None


def test_data_survives_restart(tmp_path):
    db = tmp_path / "sub" / "alerts.db"
    first = Storage(db)
    first.add(1, URL, "Book", 10, True)
    first.close()
    second = Storage(db)
    assert second.list_for_chat(1)[0].title == "Book"
    second.close()
