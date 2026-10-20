"""Tests for the Telegram layer, with fake Update objects instead of Telegram.

The fake token only has the right format. Nothing here connects to Telegram:
the application is built but never started.
"""

import asyncio
from types import SimpleNamespace

import pytest
from telegram.error import BadRequest, Forbidden, NetworkError
from telegram.ext import CommandHandler

from price_alert_bot.bot import TelegramBot, build_application, retry_once
from price_alert_bot.commands import Alert
from price_alert_bot.config import Settings

from .conftest import URL

FAKE_TOKEN = "123456:TEST-TOKEN-NOT-REAL"


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeChat:
    id = 42

    async def send_action(self, action):
        pass


def fake_update(text=""):
    return SimpleNamespace(
        effective_message=FakeMessage(text),
        effective_chat=FakeChat(),
        effective_user=SimpleNamespace(first_name="Max"),
    )


def run(coro):
    return asyncio.run(coro)


def test_application_has_all_commands_and_job(service):
    app = build_application(Settings(token=FAKE_TOKEN, check_interval_minutes=30), service)
    commands = {
        cmd
        for handler in app.handlers[0]
        if isinstance(handler, CommandHandler)
        for cmd in handler.commands
    }
    assert commands == {"start", "help", "track", "list", "remove", "check"}
    job = app.job_queue.get_jobs_by_name("price-check")[0]
    assert job.trigger.interval.total_seconds() == 30 * 60


def test_track_handler_replies(service):
    bot = TelegramBot(service, 60)
    update = fake_update()
    run(bot.track(update, SimpleNamespace(args=[URL])))
    assert "Now watching" in update.effective_message.replies[0]


def test_plain_link_is_tracked(service, storage):
    bot = TelegramBot(service, 60)
    update = fake_update(URL)
    run(bot.plain_text(update, SimpleNamespace(args=None)))
    assert storage.count_for_chat(42) == 1


def test_plain_text_gets_hint(service):
    bot = TelegramBot(service, 60)
    update = fake_update("hello")
    run(bot.plain_text(update, SimpleNamespace(args=None)))
    assert "/help" in update.effective_message.replies[0]


def test_check_job_sends_alerts(service, monkeypatch):
    sent = []

    class FakeTelegram:
        async def send_message(self, chat_id, text, **kwargs):
            sent.append((chat_id, text))

    bot = TelegramBot(service, 60)
    monkeypatch.setattr(service, "check_all", lambda: [Alert(1, "a"), Alert(2, "b")])
    run(bot.check_job(SimpleNamespace(bot=FakeTelegram())))
    assert sent == [(1, "a"), (2, "b")]


def test_retry_once_recovers_from_network_error():
    calls = []

    async def send():
        calls.append(1)
        if len(calls) == 1:
            raise NetworkError("httpx.ConnectError")
        return "ok"

    assert run(retry_once(send, delay=0)) == "ok"
    assert len(calls) == 2


def test_retry_once_does_not_retry_bad_request():
    calls = []

    async def send():
        calls.append(1)
        raise BadRequest("Can't parse entities")

    with pytest.raises(BadRequest):
        run(retry_once(send, delay=0))
    assert len(calls) == 1


def test_failing_typing_action_does_not_break_track(service):
    class BrokenChat(FakeChat):
        async def send_action(self, action):
            raise NetworkError("httpx.ConnectError")

    bot = TelegramBot(service, 60)
    update = fake_update()
    update.effective_chat = BrokenChat()
    run(bot.track(update, SimpleNamespace(args=[URL])))
    assert "Now watching" in update.effective_message.replies[0]


def test_check_job_continues_after_failed_chat(service, monkeypatch):
    sent = []

    class FlakyTelegram:
        async def send_message(self, chat_id, text, **kwargs):
            if chat_id == 1:
                raise Forbidden("bot was blocked by the user")
            sent.append(chat_id)

    bot = TelegramBot(service, 60)
    monkeypatch.setattr(service, "check_all", lambda: [Alert(1, "a"), Alert(2, "b")])
    run(bot.check_job(SimpleNamespace(bot=FlakyTelegram())))
    assert sent == [2]


def test_error_handler_logs_errors_without_update(service, caplog):
    bot = TelegramBot(service, 60)
    run(bot.on_error(None, SimpleNamespace(error=RuntimeError("boom"))))
    assert "Error while handling an update" in caplog.text
