"""Application configuration."""

import os
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """Application settings from environment variables."""

    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'usbutler.db'}")
    DEFAULT_DOOR_HOLD_TIME = float(os.getenv("DEFAULT_DOOR_HOLD_TIME", "0.5"))

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    TELEGRAM_CHAT_TOPIC_ID = os.getenv("TELEGRAM_CHAT_TOPIC_ID")

    CARD_READER_POLL_INTERVAL = float(os.getenv("CARD_READER_POLL_INTERVAL", "1"))
    DEFAULT_DOOR_ID = int(os.getenv("DEFAULT_DOOR_ID", "1"))

    MIFARE_DATA_ROTATION_ENABLED = _env_bool("MIFARE_DATA_ROTATION_ENABLED", True)
    MIFARE_DATA_BLOCK = int(os.getenv("MIFARE_DATA_BLOCK", "4"))
    MIFARE_UUID_HISTORY_LIMIT = int(os.getenv("MIFARE_UUID_HISTORY_LIMIT", "3"))
    MIFARE_WRITE_MAX_ATTEMPTS = int(os.getenv("MIFARE_WRITE_MAX_ATTEMPTS", "3"))
    MIFARE_WRITE_RETRY_DELAY_SECONDS = float(
        os.getenv("MIFARE_WRITE_RETRY_DELAY_SECONDS", "0.15")
    )
    MIFARE_CLASSIC_KEY_A = (
        os.getenv("MIFARE_CLASSIC_KEY_A", "FFFFFFFFFFFF").replace(" ", "").upper()
    )

    BUTTON_DEBOUNCE_TIME = float(os.getenv("BUTTON_DEBOUNCE_TIME", "3"))

    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
    POS_SECRET = os.getenv("POS_SECRET", "")


settings = Settings()

if settings.MIFARE_UUID_HISTORY_LIMIT < 1:
    raise ValueError("MIFARE_UUID_HISTORY_LIMIT must be at least 1")
if settings.MIFARE_WRITE_MAX_ATTEMPTS < 1:
    raise ValueError("MIFARE_WRITE_MAX_ATTEMPTS must be at least 1")
if settings.MIFARE_WRITE_RETRY_DELAY_SECONDS < 0:
    raise ValueError("MIFARE_WRITE_RETRY_DELAY_SECONDS cannot be negative")
