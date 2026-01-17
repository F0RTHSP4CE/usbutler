"""Door control service with libgpiod hardware integration."""

import datetime
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.services.auth_service import User

import gpiod
from gpiod.line import Direction, Value
import requests


logger = logging.getLogger(__name__)


class DoorEventType(str, Enum):
    OPEN = "open"
    CLOSE = "close"
    AUTO_LOCK = "auto_lock"
    COOLDOWN_SKIP = "cooldown_skip"


@dataclass(frozen=True)
class GpioSettings:
    gpio_pin: int
    active_high: bool
    gpio_chip: str

    @classmethod
    def from_env(cls) -> "GpioSettings":
        return cls(
            gpio_pin=int(os.getenv("USBUTLER_DOOR_GPIO", "17")),
            active_high=os.getenv("USBUTLER_DOOR_ACTIVE_HIGH", "1").strip().lower()
            not in {
                "0",
                "false",
                "off",
                "no",
            },
            gpio_chip=os.getenv("USBUTLER_GPIO_CHIP", "/dev/gpiochip0"),
        )


@dataclass(frozen=True)
class LedSettings:
    endpoint: Optional[str]
    message_template: str
    font: str
    timeout_ms: str
    position_x: str
    position_y: str
    request_timeout: float

    @classmethod
    def from_env(cls) -> "LedSettings":
        try:
            request_timeout = float(os.getenv("USBUTLER_LED_REQUEST_TIMEOUT", "5"))
        except (TypeError, ValueError):
            request_timeout = 5.0

        return cls(
            endpoint=os.getenv("USBUTLER_LED_ENDPOINT"),
            message_template=os.getenv(
                "USBUTLER_LED_MESSAGE_TEMPLATE", "Welcome {name}!"
            ),
            font=os.getenv("USBUTLER_LED_FONT", "BMplain"),
            timeout_ms=os.getenv("USBUTLER_LED_TIMEOUT", "500"),
            position_x=os.getenv("USBUTLER_LED_POSITION_X", "10"),
            position_y=os.getenv("USBUTLER_LED_POSITION_Y", "5"),
            request_timeout=request_timeout,
        )


@dataclass(frozen=True)
class TelegramSettings:
    chat_id: Optional[str]
    base_url: Optional[str]
    thread_id: Optional[str]
    request_timeout: float
    message_template: str

    @classmethod
    def from_env(cls) -> "TelegramSettings":
        base_url = os.getenv("USBUTLER_TG_BASE_URL")
        if not base_url:
            token = os.getenv("USBUTLER_TG_BOT_TOKEN")
            if token:
                base_url = f"https://api.telegram.org/bot{token}/sendMessage"

        try:
            request_timeout = float(os.getenv("USBUTLER_TG_REQUEST_TIMEOUT", "5"))
        except (TypeError, ValueError):
            request_timeout = 5.0

        return cls(
            chat_id=os.getenv("USBUTLER_TG_CHAT_ID"),
            base_url=base_url,
            thread_id=os.getenv("USBUTLER_TG_THREAD_ID"),
            request_timeout=request_timeout,
            message_template=os.getenv(
                "USBUTLER_TG_MESSAGE_TEMPLATE",
                "Door unlocked at {time} by {name} [{identifier_type}: {identifier}]",
            ),
        )


@dataclass(frozen=True)
class DoorServiceSettings:
    gpio: GpioSettings
    led: LedSettings
    telegram: TelegramSettings

    @classmethod
    def from_env(cls) -> "DoorServiceSettings":
        return cls(
            gpio=GpioSettings.from_env(),
            led=LedSettings.from_env(),
            telegram=TelegramSettings.from_env(),
        )


@dataclass
class DoorEvent:
    """Door event data model"""

    user: User
    event_type: DoorEventType
    timestamp: float = field(default_factory=time.time)


class DoorControlService:
    """Service for controlling the smart door lock"""

    def __init__(self, auto_lock_delay: float = 0.5):
        self.is_open = False
        self.auto_lock_delay = float(auto_lock_delay)
        self.last_user: Optional[User] = None
        self.event_history = []
        self._settings = DoorServiceSettings.from_env()
        self._chip = None
        self._line = None
        self._gpio_enabled = False
        self._state_lock = threading.Lock()
        self._auto_lock_timer: Optional[threading.Timer] = None

        self._initialize_gpio()

    def open_door(self, user: User) -> DoorEvent:
        """
        Open the door for an authenticated user
        Returns DoorEvent for logging/audit purposes
        """
        with self._state_lock:
            print(f"🔓 DOOR OPENED for {user.name} ({user.access_level})")
            self.is_open = True
            self.last_user = user
            self._set_gpio(True)
            event = DoorEvent(user, DoorEventType.OPEN)
            self.event_history.append(event)
            self._schedule_auto_lock()

        threading.Thread(
            target=self._dispatch_unlock_notifications,
            args=(event,),
            daemon=True,
        ).start()
        return event

    def lock_door(self, user: Optional[User] = None) -> DoorEvent:
        """
        Lock the door manually
        Returns DoorEvent for logging/audit purposes
        """
        with self._state_lock:
            if self._auto_lock_timer is not None:
                self._auto_lock_timer.cancel()
                self._auto_lock_timer = None
            print("🔒 DOOR LOCKED")
            self.is_open = False
            self._set_gpio(False)
            lock_user = user or self.last_user or User("unknown", "System", "system")
            event = DoorEvent(
                lock_user,
                DoorEventType.CLOSE if user else DoorEventType.AUTO_LOCK,
            )
            self.event_history.append(event)

        return event

    def _schedule_auto_lock(self):
        """Schedule automatic door locking after delay"""
        if self.auto_lock_delay <= 0:
            return
        if self._auto_lock_timer is not None:
            self._auto_lock_timer.cancel()
        print(f"Door will auto-lock in {self.auto_lock_delay} seconds...")
        self._auto_lock_timer = threading.Timer(
            self.auto_lock_delay, self._auto_lock_callback
        )
        self._auto_lock_timer.daemon = True
        self._auto_lock_timer.start()

    def _auto_lock_callback(self) -> None:
        with self._state_lock:
            self._auto_lock_timer = None
            is_open = self.is_open
        if is_open:
            self.lock_door()

    def _initialize_gpio(self) -> None:
        if gpiod is None:
            print(
                "ℹ️ gpiod module not available; door service will run in simulation mode."
            )
            return
        try:
            gpio = self._settings.gpio
            self._chip = gpiod.Chip(gpio.gpio_chip)
            line_settings = gpiod.LineSettings(direction=Direction.OUTPUT)
            self._line = self._chip.request_lines(
                config={gpio.gpio_pin: line_settings},
                consumer="usbutler",
            )
            self._gpio_enabled = True
            self._set_gpio(False)
            print(
                f"🔌 libgpiod initialized on {gpio.gpio_chip} "
                f"GPIO {gpio.gpio_pin} "
                f"({'active-high' if gpio.active_high else 'active-low'})."
            )
        except Exception as exc:
            print(f"⚠️ Failed to initialize GPIO ({exc}); running in simulation mode.")
            self._gpio_enabled = False
            self._chip = None
            self._line = None

    def _set_gpio(self, unlocked: bool) -> None:
        if not self._gpio_enabled or not self._line:
            return
        gpio = self._settings.gpio
        desired_level = (
            (Value.ACTIVE if unlocked else Value.INACTIVE)
            if gpio.active_high
            else (Value.INACTIVE if unlocked else Value.ACTIVE)
        )
        try:
            self._line.set_value(gpio.gpio_pin, desired_level)
        except Exception as exc:  # pragma: no cover - hardware failure
            print(f"⚠️ Failed to toggle GPIO {gpio.gpio_pin}: {exc}")

    def _dispatch_unlock_notifications(self, event: DoorEvent) -> None:
        for action, label in (
            (lambda: self._send_led_message(event.user), "LED welcome message"),
            (lambda: self._send_telegram_log(event), "Telegram door log"),
        ):
            try:
                action()
            except Exception as exc:  # pragma: no cover - network failure path
                logger.warning("Failed to send %s: %s", label, exc)

    def _send_led_message(self, user: User) -> None:
        settings = self._settings.led
        endpoint = settings.endpoint
        if not endpoint:
            return
        try:
            text = settings.message_template.format(name=user.name)
        except Exception:
            text = f"Welcome {user.name}!"

        query_params = {
            "text": text,
            "font": settings.font,
            "timeout": settings.timeout_ms,
            "x": settings.position_x,
            "y": settings.position_y,
        }

        requests.post(
            endpoint,
            params=query_params,
            data=b"",
            timeout=settings.request_timeout,
        )

    def _send_telegram_log(self, event: DoorEvent) -> None:
        settings = self._settings.telegram
        if not settings.chat_id or not settings.base_url:
            return

        timestamp = datetime.datetime.fromtimestamp(
            event.timestamp, tz=datetime.timezone.utc
        ).astimezone()
        timestamp_text = timestamp.strftime("%Y-%m-%d %H:%M:%S %Z")

        identifier = (
            event.user.identifiers[0] if event.user and event.user.identifiers else None
        )
        identifier_type = identifier.type if identifier else "unknown"
        identifier_masked = identifier.mask() if identifier else "unknown"
        try:
            message_text = settings.message_template.format(
                time=timestamp_text,
                name=event.user.name if event.user else "Unknown",
                identifier_type=identifier_type,
                identifier=identifier_masked,
            )
        except Exception:
            message_text = (
                f"Door unlocked at {timestamp_text} by {event.user.name if event.user else 'Unknown'} "
                f"[{identifier_type}: {identifier_masked}]"
            )

        payload = {"chat_id": settings.chat_id, "text": message_text}
        if settings.thread_id:
            payload["message_thread_id"] = settings.thread_id

        requests.post(
            settings.base_url,
            data=payload,
            timeout=settings.request_timeout,
        )
