"""Notification service for sending alerts."""

import logging
from typing import Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending notifications to various endpoints."""

    def __init__(
        self,
        internal_webhook_url: Optional[str] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
    ):
        self.internal_webhook_url = (
            internal_webhook_url or settings.INTERNAL_WEBHOOK_URL
        )
        self.telegram_bot_token = telegram_bot_token or settings.TELEGRAM_BOT_TOKEN
        self.telegram_chat_id = telegram_chat_id or settings.TELEGRAM_CHAT_ID

    def send_internal_notification(
        self,
        door_name: str,
        username: Optional[str] = None,
        success: bool = True,
    ) -> bool:
        """Send notification to internal HTTP endpoint."""
        if not self.internal_webhook_url:
            logger.debug("Internal webhook URL not configured, skipping notification")
            return False

        try:
            if success:
                if username:
                    message = f"🚪 Door '{door_name}' opened for user '{username}'"
                else:
                    message = f"🚪 Door '{door_name}' opened"
            else:
                message = f"❌ Failed to open door '{door_name}'"

            payload = {
                "door_name": door_name,
                "username": username,
                "success": success,
                "message": message,
            }

            response = requests.post(
                self.internal_webhook_url,
                json=payload,
                timeout=5,
            )
            response.raise_for_status()
            logger.info(f"Internal notification sent: {message}")
            return True

        except requests.RequestException as e:
            logger.error(f"Failed to send internal notification: {e}")
            return False

    def send_telegram_notification(
        self,
        door_name: str,
        username: Optional[str] = None,
        success: bool = True,
    ) -> bool:
        """Send notification to Telegram channel via bot API."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.debug("Telegram not configured, skipping notification")
            return False

        try:
            if success:
                if username:
                    message = f"🚪 Door *{door_name}* opened for user *{username}*"
                else:
                    message = f"🚪 Door *{door_name}* opened"
            else:
                message = f"❌ Failed to open door *{door_name}*"

            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Telegram notification sent: {message}")
            return True

        except requests.RequestException as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            return False

    def notify_door_opened(
        self,
        door_name: str,
        username: Optional[str] = None,
        success: bool = True,
    ) -> None:
        """Send notifications to all configured channels."""
        self.send_internal_notification(door_name, username, success)
        self.send_telegram_notification(door_name, username, success)

    def notify_button_pressed(
        self,
        door_name: str,
        gpio_pin: int,
    ) -> None:
        """Send notification when external button is pressed."""
        self._send_button_internal_notification(door_name, gpio_pin)
        self._send_button_telegram_notification(door_name, gpio_pin)

    def _send_button_internal_notification(
        self,
        door_name: str,
        gpio_pin: int,
    ) -> bool:
        """Send button press notification to internal HTTP endpoint."""
        if not self.internal_webhook_url:
            logger.debug("Internal webhook URL not configured, skipping notification")
            return False

        try:
            message = (
                f"🔘 External button pressed for door '{door_name}' (GPIO {gpio_pin})"
            )

            payload = {
                "door_name": door_name,
                "gpio_pin": gpio_pin,
                "event": "button_pressed",
                "message": message,
            }

            response = requests.post(
                self.internal_webhook_url,
                json=payload,
                timeout=5,
            )
            response.raise_for_status()
            logger.info(f"Internal notification sent: {message}")
            return True

        except requests.RequestException as e:
            logger.error(f"Failed to send internal notification: {e}")
            return False

    def _send_button_telegram_notification(
        self,
        door_name: str,
        gpio_pin: int,
    ) -> bool:
        """Send button press notification to Telegram."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.debug("Telegram not configured, skipping notification")
            return False

        try:
            message = (
                f"🔘 External button pressed for door *{door_name}* (GPIO {gpio_pin})"
            )

            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Telegram notification sent: {message}")
            return True

        except requests.RequestException as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            return False
