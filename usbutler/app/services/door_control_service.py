"""Door control service for GPIO operations with button monitoring."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Callable, Dict, Generator, List, Optional

from app.config import settings
from app.models.door import Door
from app.models.door_event import DoorEventType
from app.services.notification_service import NotificationService

if TYPE_CHECKING:
    from app.dependencies import Services

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="door_")

# Type alias for session factory
SessionFactory = Callable[[], AbstractContextManager["Services"]]


class DoorControlService:
    """Controls physical doors via GPIO with button monitoring."""

    def __init__(
        self,
        notification_service: NotificationService,
        session_factory: SessionFactory,
    ):
        self.notification_service = notification_service
        self.session_factory = session_factory
        self._gpio_available = self._check_gpio()

        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._doors: Dict[int, Door] = {}  # gpio_pin -> Door
        self._pin_locks: Dict[int, threading.Lock] = {}
        self._last_button_press: Dict[int, float] = {}
        self._pin_in_output: Dict[int, bool] = {}
        self._pin_released: Dict[int, threading.Event] = {}

    def _check_gpio(self) -> bool:
        try:
            import gpiod

            return True
        except ImportError:
            logger.warning("gpiod not available, GPIO will be simulated")
            return False

    def _persist_event(
        self,
        door_id: int,
        event_type: DoorEventType,
        username: Optional[str] = None,
        user_id: Optional[int] = None,
        on_behalf_of: Optional[str] = None,
    ):
        try:
            with self.session_factory() as services:
                services.door_events.create(
                    door_id=door_id,
                    event_type=event_type,
                    username=username,
                    user_id=user_id,
                    on_behalf_of=on_behalf_of,
                )
        except Exception as e:
            logger.error(f"Failed to persist door event: {e}", exc_info=True)

    def _persist_event_async(
        self,
        door_id: int,
        event_type: DoorEventType,
        username: Optional[str] = None,
        user_id: Optional[int] = None,
        on_behalf_of: Optional[str] = None,
    ):
        """Persist event asynchronously for use in event loops/monitoring."""
        _executor.submit(self._persist_event, door_id, event_type, username, user_id, on_behalf_of)

    def get_last_door_event(self) -> Optional[dict]:
        """Get the most recent door event from database."""
        try:
            with self.session_factory() as services:
                events, _ = services.door_events.get_history(page=1, page_size=1)
                if not events:
                    return None

                event = events[0]
                door = services.doors.get_by_id(event.door_id)

                return {
                    "door_name": door.name if door else f"Door #{event.door_id}",
                    "door_id": event.door_id,
                    "gpio_pin": door.gpio_pin if door else 0,
                    "event_type": event.event_type.value,
                    "username": event.username,
                    "on_behalf_of": event.on_behalf_of,
                    "timestamp": event.timestamp,
                }
        except Exception as e:
            logger.error(f"Failed to get last door event: {e}")
            return None

    def start_button_monitoring(self, doors: List[Door]) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        for door in doors:
            pin = door.gpio_pin
            self._doors[pin] = door
            self._pin_locks[pin] = threading.Lock()
            self._last_button_press[pin] = 0
            self._pin_in_output[pin] = False
            self._pin_released[pin] = threading.Event()
            self._pin_released[pin].set()

        if not self._doors:
            return

        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info(f"Button monitoring started for {len(self._doors)} doors")

    def stop_button_monitoring(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._stop_event.set()
            self._monitor_thread.join(timeout=2.0)
        self._doors.clear()
        self._pin_locks.clear()

    def update_monitored_doors(self, doors: List[Door]) -> None:
        new_pins = {d.gpio_pin for d in doors}
        old_pins = set(self._doors.keys())

        for pin in old_pins - new_pins:
            self._doors.pop(pin, None)
            self._pin_locks.pop(pin, None)
            self._last_button_press.pop(pin, None)
            self._pin_in_output.pop(pin, None)
            self._pin_released.pop(pin, None)

        for door in doors:
            pin = door.gpio_pin
            if pin not in self._doors:
                self._doors[pin] = door
                self._pin_locks[pin] = threading.Lock()
                self._last_button_press[pin] = 0
                self._pin_in_output[pin] = False
                self._pin_released[pin] = threading.Event()
                self._pin_released[pin].set()
            else:
                self._doors[pin] = door

    def _monitor_loop(self) -> None:
        if not self._gpio_available:
            logger.warning("GPIO not available, button monitoring disabled")
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=1.0)
            return

        import gpiod
        from gpiod.line import Direction, Bias, Edge

        logger.info("Button monitor thread started")

        while not self._stop_event.is_set():
            pins = {
                p: d for p, d in self._doors.items() if not self._pin_in_output.get(p)
            }
            if not pins:
                self._stop_event.wait(timeout=0.5)
                continue

            try:
                config = {
                    pin: gpiod.LineSettings(
                        direction=Direction.INPUT,
                        bias=Bias.PULL_UP,
                        edge_detection=Edge.FALLING,
                        debounce_period=timedelta(milliseconds=50),
                    )
                    for pin in pins
                }

                logger.info(
                    f"Requesting GPIO lines for button monitoring: {list(pins.keys())}"
                )
                with gpiod.request_lines(
                    "/dev/gpiochip0", consumer="usbutler-btn", config=config
                ) as req:
                    for pin in pins:
                        if ev := self._pin_released.get(pin):
                            ev.clear()

                    logger.info(
                        f"Button monitoring active for pins: {list(pins.keys())}"
                    )

                    while not self._stop_event.is_set():
                        # Break if any monitored pin needs output mode
                        if any(self._pin_in_output.get(p) for p in pins):
                            logger.debug("Releasing GPIO lines for door output")
                            break

                        # Break if there are pins that should be monitored but aren't
                        available_pins = {
                            p
                            for p, d in self._doors.items()
                            if not self._pin_in_output.get(p)
                        }
                        if available_pins != set(pins.keys()):
                            logger.debug("Pin set changed, re-requesting GPIO lines")
                            break

                        if req.wait_edge_events(timeout=timedelta(milliseconds=500)):
                            events = req.read_edge_events()
                            for event in events:
                                pin = event.line_offset
                                door = pins.get(pin)
                                if not door or self._pin_in_output.get(pin):
                                    continue

                                now = time.time()
                                if (
                                    now - self._last_button_press.get(pin, 0)
                                    > settings.BUTTON_DEBOUNCE_TIME
                                ):
                                    self._last_button_press[pin] = now
                                    logger.info(
                                        f"Button press on GPIO {pin} for '{door.name}'"
                                    )
                                    self._persist_event_async(
                                        door.id, DoorEventType.BUTTON
                                    )
                                    self.notification_service.notify_button_pressed_async(
                                        door.name, pin
                                    )

                for pin in pins:
                    if ev := self._pin_released.get(pin):
                        ev.set()

            except Exception as e:
                logger.error(f"Button monitor error: {e}")
                for pin in pins:
                    if ev := self._pin_released.get(pin):
                        ev.set()
                self._stop_event.wait(timeout=1.0)

    def _open_door_sync(
        self,
        door: Door,
        username: Optional[str] = None,
        event_type: DoorEventType = DoorEventType.API,
        user_id: Optional[int] = None,
        on_behalf_of: Optional[str] = None,
    ) -> bool:
        logger.info(f"Opening door '{door.name}' (pin={door.gpio_pin})")
        pin = door.gpio_pin
        lock = self._pin_locks.get(pin)
        released = self._pin_released.get(pin)

        try:
            if lock:
                lock.acquire()
            self._pin_in_output[pin] = True
            if released:
                if not released.wait(timeout=5.0):
                    logger.error(f"Timeout waiting for button monitor to release pin {pin}")
                    success = False
                else:
                    success = (
                        self._control_gpio(door)
                        if self._gpio_available
                        else self._simulate_gpio(door)
                    )
            else:
                success = (
                    self._control_gpio(door)
                    if self._gpio_available
                    else self._simulate_gpio(door)
                )
        except Exception as e:
            logger.error(f"Error opening door '{door.name}': {e}")
            success = False
        finally:
            self._pin_in_output[pin] = False
            if lock:
                lock.release()

        self._persist_event(door.id, event_type, username, user_id, on_behalf_of)
        self.notification_service.notify_door_opened_async(door.name, username, success, on_behalf_of)
        return success

    def _control_gpio(self, door: Door) -> bool:
        import gpiod
        from gpiod.line import Direction, Value

        active = Value.INACTIVE if door.gpio_active_low else Value.ACTIVE
        inactive = Value.ACTIVE if door.gpio_active_low else Value.INACTIVE

        try:
            with gpiod.request_lines(
                "/dev/gpiochip0",
                consumer="usbutler-door",
                config={door.gpio_pin: gpiod.LineSettings(direction=Direction.OUTPUT)},
            ) as req:
                req.set_value(door.gpio_pin, active)
                time.sleep(door.open_hold_time)
                req.set_value(door.gpio_pin, inactive)
            return True
        except Exception as e:
            logger.error(f"GPIO error for '{door.name}': {e}")
            return False

    def _simulate_gpio(self, door: Door) -> bool:
        logger.info(f"[SIM] GPIO {door.gpio_pin} active")
        time.sleep(door.open_hold_time)
        logger.info(f"[SIM] GPIO {door.gpio_pin} inactive")
        return True

    def open_door_async(
        self,
        door: Door,
        username: Optional[str] = None,
        event_type: DoorEventType = DoorEventType.API,
        user_id: Optional[int] = None,
        on_behalf_of: Optional[str] = None,
    ) -> bool:
        _executor.submit(self._open_door_sync, door, username, event_type, user_id, on_behalf_of)
        return True

    def open_door_blocking(
        self,
        door: Door,
        username: Optional[str] = None,
        event_type: DoorEventType = DoorEventType.API,
        user_id: Optional[int] = None,
        on_behalf_of: Optional[str] = None,
    ) -> bool:
        return self._open_door_sync(door, username, event_type, user_id, on_behalf_of)

    def open_door_for_card(self, door: Door, username: Optional[str] = None) -> bool:
        return self.open_door_async(door, username, DoorEventType.CARD)
