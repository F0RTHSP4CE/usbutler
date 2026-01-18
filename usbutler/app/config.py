"""Application configuration."""

import os
from pathlib import Path


class Settings:
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{Path(__file__).parent.parent / 'data' / 'usbutler.db'}",
    )

    # Door control
    DEFAULT_DOOR_HOLD_TIME: float = float(os.getenv("DEFAULT_DOOR_HOLD_TIME", "0.5"))

    # Notifications
    INTERNAL_WEBHOOK_URL: str = os.getenv("INTERNAL_WEBHOOK_URL", "")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Card reader
    CARD_READER_POLL_INTERVAL: float = float(
        os.getenv("CARD_READER_POLL_INTERVAL", "1")
    )
    DEFAULT_DOOR_ID: int = int(os.getenv("DEFAULT_DOOR_ID", "1"))

    # API Authentication (used for both API and UI)
    API_PASSWORD: str = os.getenv("API_PASSWORD", "")


settings = Settings()
