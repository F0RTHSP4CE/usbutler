"""Notification service for sending alerts."""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="notify_")


class NotificationService:
    """Service for sending Telegram notifications."""

    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID

    def _send_telegram(self, message: str) -> bool:
        if not self.bot_token or not self.chat_id:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            response = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")
            return False

    def notify_door_opened_async(
        self, door_name: str, username: Optional[str] = None, success: bool = True
    ) -> None:
        if success:
            msg = f"🚪 Door *{door_name}* opened" + (
                f" for *{username}*" if username else ""
            )
        else:
            msg = f"❌ Failed to open door *{door_name}*"
        _executor.submit(self._send_telegram, msg)

    def notify_button_pressed_async(self, door_name: str, gpio_pin: int) -> None:
        msg = f"🔘 Button pressed for door *{door_name}* (GPIO {gpio_pin})"
        _executor.submit(self._send_telegram, msg)
