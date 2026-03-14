"""Application configuration."""

import os
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings:
    """Application settings from environment variables."""

    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'usbutler.db'}")
    DEFAULT_DOOR_HOLD_TIME = float(os.getenv("DEFAULT_DOOR_HOLD_TIME", "0.5"))

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    TELEGRAM_CHAT_TOPIC_ID = os.getenv("TELEGRAM_CHAT_TOPIC_ID")

    CARD_READER_POLL_INTERVAL = float(os.getenv("CARD_READER_POLL_INTERVAL", "1"))
    DEFAULT_DOOR_ID = int(os.getenv("DEFAULT_DOOR_ID", "1"))

    BUTTON_DEBOUNCE_TIME = float(os.getenv("BUTTON_DEBOUNCE_TIME", "3"))

    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
    POS_SECRET = os.getenv("POS_SECRET", "")


settings = Settings()
