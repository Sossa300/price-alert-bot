"""Settings from environment variables (or a local .env file).

The bot token is a password: whoever has it controls the bot. It therefore
lives in .env, which is listed in .gitignore and never committed. The repo
only ships .env.example with placeholder values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when a required setting is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    token: str
    db_path: Path = Path("data/alerts.db")
    check_interval_minutes: float = 60.0
    max_items_per_chat: int = 20
    request_delay: float = 1.0
    log_level: str = "INFO"
    force_ipv4: bool = False


def _flag(env: dict, name: str) -> bool:
    return (env.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _number(env: dict, name: str, default: float, minimum: float) -> float:
    raw = env.get(name)
    if raw in (None, ""):
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}")
    return value


def load_settings(env: dict | None = None, dotenv_path: str | None = ".env") -> Settings:
    """Build Settings from env (default: os.environ after reading .env).

    Passing env explicitly lets the tests check every rule without touching
    the real environment or needing a real token.
    """
    if env is None:
        if dotenv_path:
            load_dotenv(dotenv_path)
        env = dict(os.environ)

    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token.startswith("your-"):
        raise ConfigError(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and paste "
            "the token you got from @BotFather."
        )

    return Settings(
        token=token,
        db_path=Path(env.get("DB_PATH") or "data/alerts.db"),
        # Minimum 1 minute: checking a shop every few seconds is impolite.
        check_interval_minutes=_number(env, "CHECK_INTERVAL_MINUTES", 60.0, 1.0),
        max_items_per_chat=int(_number(env, "MAX_ITEMS_PER_CHAT", 20, 1)),
        request_delay=_number(env, "REQUEST_DELAY", 1.0, 0.0),
        log_level=(env.get("LOG_LEVEL") or "INFO").upper(),
        force_ipv4=_flag(env, "FORCE_IPV4"),
    )
