"""The Telegram layer: connects Telegram updates to BotService.

This file only translates: "user sent /track ..." -> service.track(...)
-> send the reply back. All decisions live in commands.py. To build the same
bot for Discord you would replace this file with a discord.py version.

python-telegram-bot is asynchronous (async/await), but scraping and SQLite
are blocking. asyncio.to_thread() runs them in a worker thread, so the bot
stays responsive while a page downloads. The lock makes sure only one
database job runs at a time.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial

import httpx
from telegram import BotCommand, LinkPreviewOptions, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, NetworkError, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from .commands import BotService
from .config import Settings
from .prices import build_fetcher
from .storage import Storage

log = logging.getLogger(__name__)

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

# Shown in Telegram's "/" menu next to the text field.
MENU = [
    BotCommand("track", "Watch a product: /track <link> [target]"),
    BotCommand("list", "Show your watchlist"),
    BotCommand("remove", "Stop watching: /remove <number>"),
    BotCommand("check", "Check your products now"),
    BotCommand("help", "How to use this bot"),
]


async def retry_once(send, delay: float = 1.0):
    """Call send() and retry once after a network hiccup.

    Idle connections to Telegram are sometimes closed silently by routers or
    proxies; the first request afterwards then fails with a NetworkError,
    the second works. BadRequest (e.g. broken HTML) is also a NetworkError in
    python-telegram-bot, but retrying would not help, so it is raised at once.
    """
    try:
        return await send()
    except NetworkError as exc:
        if isinstance(exc, BadRequest):
            raise
        log.warning("Network error (%s), retrying once", exc)
        await asyncio.sleep(delay)
        return await send()


class TelegramBot:
    def __init__(self, service: BotService, check_interval_minutes: float) -> None:
        self.service = service
        self.interval = check_interval_minutes
        self.lock = asyncio.Lock()

    async def run(self, func, *args):
        """Run a blocking service method in a worker thread, one at a time."""
        async with self.lock:
            return await asyncio.to_thread(func, *args)

    async def reply(self, update: Update, text: str) -> None:
        await retry_once(lambda: update.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW
        ))

    async def typing(self, update: Update) -> None:
        """Show "typing..." while we work. Purely cosmetic, so errors are ignored."""
        try:
            await update.effective_chat.send_action(ChatAction.TYPING)
        except TelegramError as exc:
            log.debug("Could not send typing action: %s", exc)

    # -------------------------------------------------------------- handlers

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.reply(update, self.service.start(update.effective_user.first_name))

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.reply(update, self.service.help())

    async def track(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.typing(update)
        chat_id = update.effective_chat.id
        await self.reply(update, await self.run(self.service.track, chat_id, context.args))

    async def list_items(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.reply(update, await self.run(self.service.list_items, update.effective_chat.id))

    async def remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        await self.reply(update, await self.run(self.service.remove, chat_id, context.args))

    async def check(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.typing(update)
        await self.reply(update, await self.run(self.service.check_chat, update.effective_chat.id))

    async def plain_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """A link without a command is treated like /track <link>."""
        text = update.effective_message.text.strip()
        if text.startswith(("http://", "https://")):
            context.args = text.split()
            await self.track(update, context)
        else:
            await self.reply(update, "Send me a product link or use /help to see what I can do.")

    async def unknown(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.reply(update, "I don't know that command. Try /help")

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log every unexpected error and tell the user instead of going silent."""
        log.error("Error while handling an update", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("😕 Something went wrong. Please try again later.")

    # --------------------------------------------------------- scheduled job

    async def check_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        alerts = await self.run(self.service.check_all)
        for alert in alerts:
            try:
                await retry_once(lambda: context.bot.send_message(
                    alert.chat_id, alert.text,
                    parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW,
                ))
            except Forbidden:
                log.info("Chat %s blocked the bot, skipping alert", alert.chat_id)
            except TelegramError as exc:  # one failed chat must not stop the others
                log.error("Could not send alert to chat %s: %s", alert.chat_id, exc)


def make_request(force_ipv4: bool = False) -> HTTPXRequest:
    """HTTP client for the Telegram API that survives a shaky network.

    retries=3 repeats failed connection attempts (not whole requests), and
    local_address="0.0.0.0" forces IPv4 when the IPv6 route is unreliable.
    """
    transport = httpx.AsyncHTTPTransport(
        retries=3,
        local_address="0.0.0.0" if force_ipv4 else None,
        limits=httpx.Limits(max_connections=32),
    )
    return HTTPXRequest(connect_timeout=10.0, read_timeout=10.0,
                        httpx_kwargs={"transport": transport})


async def _post_init(app: Application) -> None:
    await app.bot.set_my_commands(MENU)
    log.info("Bot @%s is running", app.bot.username)


def build_application(settings: Settings, service: BotService | None = None) -> Application:
    """Create the Telegram application with all handlers and the scheduled check."""
    if service is None:
        service = BotService(
            Storage(settings.db_path),
            build_fetcher(settings.request_delay),
            max_items_per_chat=settings.max_items_per_chat,
            check_interval_minutes=settings.check_interval_minutes,
        )
    bot = TelegramBot(service, settings.check_interval_minutes)

    app = (
        ApplicationBuilder()
        .token(settings.token)
        .request(make_request(settings.force_ipv4))
        .get_updates_request(make_request(settings.force_ipv4))  # polling uses its own connection
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("help", bot.help))
    app.add_handler(CommandHandler("track", bot.track))
    app.add_handler(CommandHandler("list", bot.list_items))
    app.add_handler(CommandHandler("remove", bot.remove))
    app.add_handler(CommandHandler("check", bot.check))
    app.add_handler(MessageHandler(filters.COMMAND, bot.unknown))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.plain_text))
    app.add_error_handler(bot.on_error)

    # The JobQueue calls check_job every N minutes; the first run after 1 minute.
    app.job_queue.run_repeating(
        bot.check_job, interval=settings.check_interval_minutes * 60, first=60, name="price-check"
    )
    return app
