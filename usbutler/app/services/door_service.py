"""Door control service with libgpiod hardware integration."""

import datetime
import logging
import os
import threading
import time
from typing import Optional
from urllib import parse, request

from app.services.auth_service import User

try:
    import gpiod  # type: ignore
    from gpiod.line import Direction, Value  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    gpiod = None
    Direction = None  # type: ignore
    Value = None  # type: ignore


logger = logging.getLogger(__name__)


class DoorEvent:
    """Door event data model"""

    def __init__(self, user: User, event_type: str, timestamp: Optional[float] = None):
        self.user = user
        self.event_type = event_type  # 'open', 'close', 'auto_lock', 'cooldown_skip'
        self.timestamp = timestamp or time.time()


class DoorControlService:
    """Service for controlling the smart door lock"""

    def __init__(self, auto_lock_delay: float = 3):
        self.is_open = False
        self.auto_lock_delay = float(auto_lock_delay)
        self.last_user: Optional[User] = None
        self.event_history = []
        try:
            reopen_delay = float(os.getenv("USBUTLER_DOOR_REOPEN_DELAY", "5"))
        except (TypeError, ValueError):
            reopen_delay = 5.0
        self._repeat_open_cooldown = max(0.0, reopen_delay)
        self._last_open_by_identifier: dict[str, float] = {}

        self._gpio_pin = int(os.getenv("USBUTLER_DOOR_GPIO", "17"))
        self._active_high = os.getenv(
            "USBUTLER_DOOR_ACTIVE_HIGH", "1"
        ).strip().lower() not in {
            "0",
            "false",
            "off",
            "no",
        }
        self._gpio_chip = os.getenv("USBUTLER_GPIO_CHIP", "/dev/gpiochip0")

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
        identifier_key = self._get_identifier_key(user)
        cooldown = self._repeat_open_cooldown

        with self._state_lock:
            now = time.time()
            last_time = self._last_open_by_identifier.get(identifier_key)
            if cooldown > 0 and last_time is not None and now - last_time < cooldown:
                remaining = cooldown - (now - last_time)
                print(
                    f"⏱️ Door reopen cooldown active for {user.name} ({user.access_level}); "
                    f"skipping unlock ({remaining:.1f}s remaining)."
                )
                event = DoorEvent(user, "cooldown_skip", timestamp=now)
                self.event_history.append(event)
                return event

            print(f"🔓 DOOR OPENED for {user.name} ({user.access_level})")
            self.is_open = True
            self.last_user = user
            self._set_gpio(True)

            event = DoorEvent(user, "open")
            self.event_history.append(event)
            self._last_open_by_identifier[identifier_key] = event.timestamp

            # Schedule auto-lock
            self._schedule_auto_lock()

        if event.event_type == "open":
            self._notify_unlock(event)
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

            # Use last user if no user specified (for auto-lock)
            lock_user = user or self.last_user or User("unknown", "System", "system")
            event = DoorEvent(lock_user, "close" if user else "auto_lock")
            self.event_history.append(event)

        return event

    def get_door_status(self) -> dict:
        """Get current door status"""
        return {
            "is_open": self.is_open,
            "last_user": self.last_user.name if self.last_user else None,
            "auto_lock_delay": self.auto_lock_delay,
        }

    def get_recent_events(self, count: int = 10) -> list:
        """Get recent door events for audit/logging"""
        return self.event_history[-count:] if self.event_history else []

    def set_auto_lock_delay(self, delay: float):
        """Set the auto-lock delay in seconds"""
        self.auto_lock_delay = float(delay)

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
        should_lock = False
        with self._state_lock:
            self._auto_lock_timer = None
            if self.is_open:
                should_lock = True
        if should_lock:
            self.lock_door()

    def _initialize_gpio(self) -> None:
        if gpiod is None:
            print(
                "ℹ️ gpiod module not available; door service will run in simulation mode."
            )
            return
        try:
            self._chip = gpiod.Chip(self._gpio_chip)  # type: ignore
            line_settings = gpiod.LineSettings(direction=Direction.OUTPUT)  # type: ignore
            self._line = self._chip.request_lines(  # type: ignore
                config={self._gpio_pin: line_settings}, consumer="usbutler"
            )
            self._gpio_enabled = True
            self._set_gpio(False)
            print(
                f"🔌 libgpiod initialized on {self._gpio_chip} GPIO {self._gpio_pin} "
                f"({'active-high' if self._active_high else 'active-low'})."
            )
        except Exception as exc:
            print(f"⚠️ Failed to initialize GPIO ({exc}); running in simulation mode.")
            self._gpio_enabled = False
            self._chip = None
            self._line = None

    def _set_gpio(self, unlocked: bool) -> None:
        if not self._gpio_enabled or not self._line:
            return
        if unlocked:
            desired_level = Value.ACTIVE if self._active_high else Value.INACTIVE  # type: ignore
        else:
            desired_level = Value.INACTIVE if self._active_high else Value.ACTIVE  # type: ignore
        try:
            self._line.set_value(self._gpio_pin, desired_level)  # type: ignore
        except Exception as exc:  # pragma: no cover - hardware failure
            print(f"⚠️ Failed to toggle GPIO {self._gpio_pin}: {exc}")

    def _notify_unlock(self, event: DoorEvent) -> None:
        notifier_thread = threading.Thread(
            target=self._dispatch_unlock_notifications,
            args=(event,),
            daemon=True,
        )
        notifier_thread.start()

    def _get_identifier_key(self, user: User) -> str:
        identifier = user.primary_identifier()
        if identifier and identifier.value:
            return identifier.value
        return user.user_id

    def _dispatch_unlock_notifications(self, event: DoorEvent) -> None:
        try:
            self._send_led_message(event.user)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.warning("Failed to send LED welcome message: %s", exc)

        try:
            self._send_telegram_log(event)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.warning("Failed to send Telegram door log: %s", exc)

    def _send_led_message(self, user: User) -> None:
        endpoint = os.getenv("USBUTLER_LED_ENDPOINT")
        if not endpoint:
            return

        message_template = os.getenv("USBUTLER_LED_MESSAGE_TEMPLATE", "Welcome {name}!")
        font = os.getenv("USBUTLER_LED_FONT", "BMplain")
        timeout_ms = os.getenv("USBUTLER_LED_TIMEOUT", "500")
        position_x = os.getenv("USBUTLER_LED_POSITION_X", "10")
        position_y = os.getenv("USBUTLER_LED_POSITION_Y", "5")
        try:
            request_timeout = float(os.getenv("USBUTLER_LED_REQUEST_TIMEOUT", "5"))
        except (TypeError, ValueError):
            request_timeout = 5.0

        try:
            text = message_template.format(name=user.name)
        except Exception:
            text = f"Welcome {user.name}!"

        query_params = {
            "text": text,
            "font": font,
            "timeout": timeout_ms,
            "x": position_x,
            "y": position_y,
        }

        encoded_query = parse.urlencode(query_params, quote_via=parse.quote_plus)
        parsed_endpoint = parse.urlparse(endpoint)
        combined_query = "&".join(filter(None, [parsed_endpoint.query, encoded_query]))
        url = parse.urlunparse(parsed_endpoint._replace(query=combined_query))

        req = request.Request(url, data=b"", method="POST")
        request.urlopen(req, timeout=request_timeout)

    def _send_telegram_log(self, event: DoorEvent) -> None:
        chat_id = os.getenv("USBUTLER_TG_CHAT_ID")
        if not chat_id:
            return

        base_url = os.getenv("USBUTLER_TG_BASE_URL")
        if not base_url:
            token = os.getenv("USBUTLER_TG_BOT_TOKEN")
            if not token:
                return
            base_url = f"https://api.telegram.org/bot{token}/sendMessage"

        thread_id = os.getenv("USBUTLER_TG_THREAD_ID")
        try:
            request_timeout = float(os.getenv("USBUTLER_TG_REQUEST_TIMEOUT", "5"))
        except (TypeError, ValueError):
            request_timeout = 5.0

        timestamp = datetime.datetime.fromtimestamp(
            event.timestamp, tz=datetime.timezone.utc
        ).astimezone()
        timestamp_text = timestamp.strftime("%Y-%m-%d %H:%M:%S %Z")

        identifier = event.user.primary_identifier() if event.user else None
        identifier_type = identifier.type if identifier else "unknown"
        identifier_masked = identifier.mask() if identifier else "unknown"

        message_template = os.getenv(
            "USBUTLER_TG_MESSAGE_TEMPLATE",
            "Door unlocked at {time} by {name} [{identifier_type}: {identifier}]",
        )

        try:
            message_text = message_template.format(
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

        payload = {"chat_id": chat_id, "text": message_text}
        if thread_id:
            payload["message_thread_id"] = thread_id

        encoded_payload = parse.urlencode(payload).encode("utf-8")
        req = request.Request(base_url, data=encoded_payload, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        request.urlopen(req, timeout=request_timeout)
