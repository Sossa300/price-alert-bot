"""Start the bot:  python main.py

Stop it with Ctrl+C. Settings come from .env (see .env.example).
"""

import logging
import sys

from price_alert_bot.bot import build_application
from price_alert_bot.config import ConfigError, load_settings


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    # httpx logs every Telegram request (with the token in the URL!) at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # bootstrap_retries: if Telegram is briefly unreachable at start, try again
    # a few times instead of quitting immediately.
    build_application(settings).run_polling(bootstrap_retries=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
