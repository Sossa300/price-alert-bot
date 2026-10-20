from pathlib import Path

import pytest

from price_alert_bot.config import ConfigError, load_settings

TOKEN = "123456:TEST-TOKEN-NOT-REAL"


def test_defaults():
    s = load_settings({"TELEGRAM_BOT_TOKEN": TOKEN})
    assert s.token == TOKEN
    assert s.db_path == Path("data/alerts.db")
    assert s.check_interval_minutes == 60
    assert s.max_items_per_chat == 20
    assert s.log_level == "INFO"


def test_values_from_env():
    s = load_settings({
        "TELEGRAM_BOT_TOKEN": f"  {TOKEN} ",
        "CHECK_INTERVAL_MINUTES": "15",
        "DB_PATH": "x/y.db",
        "MAX_ITEMS_PER_CHAT": "5",
        "REQUEST_DELAY": "0.5",
        "LOG_LEVEL": "debug",
    })
    assert s.token == TOKEN
    assert s.check_interval_minutes == 15
    assert s.db_path == Path("x/y.db")
    assert s.max_items_per_chat == 5
    assert s.request_delay == 0.5
    assert s.log_level == "DEBUG"


@pytest.mark.parametrize("value, expected", [
    ("true", True), ("1", True), ("YES", True), ("false", False), ("", False), (None, False),
])
def test_force_ipv4_flag(value, expected):
    env = {"TELEGRAM_BOT_TOKEN": TOKEN}
    if value is not None:
        env["FORCE_IPV4"] = value
    assert load_settings(env).force_ipv4 is expected


@pytest.mark.parametrize("token",["", "   ", "your-token-from-botfather"])
def test_missing_token(token):
    with pytest.raises(ConfigError, match="BotFather"):
        load_settings({"TELEGRAM_BOT_TOKEN": token})


def test_no_token_key_at_all():
    with pytest.raises(ConfigError):
        load_settings({})


@pytest.mark.parametrize("value", ["abc", "0.5", "-1"])
def test_bad_interval(value):
    with pytest.raises(ConfigError, match="CHECK_INTERVAL_MINUTES"):
        load_settings({"TELEGRAM_BOT_TOKEN": TOKEN, "CHECK_INTERVAL_MINUTES": value})


def test_reads_dotenv_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nCHECK_INTERVAL_MINUTES=5\n")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("CHECK_INTERVAL_MINUTES", raising=False)
    s = load_settings(dotenv_path=str(env_file))
    assert s.token == TOKEN
    assert s.check_interval_minutes == 5
