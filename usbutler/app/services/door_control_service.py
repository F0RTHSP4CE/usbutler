"""Door control service for GPIO operations with button monitoring."""

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from app.config import settings
from app.models.door import Door
from app.models.door_event import DoorEventType
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

# Thread pool for non-blocking door operations
_door_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="door_control_")


@dataclass
class LastDoorEvent:
    """Information about the last door event."""

    door_name: str
    door_id: int
    gpio_pin: int
    event_type: DoorEventType
    username: Optional[str]
    timestamp: datetime


class DoorControlService:
    """Service for controlling physical doors via GPIO with button monitoring.

    This service operates GPIO pins in input mode by default to detect button presses.
    When a door open is requested via API, it temporarily switches to output mode,
    triggers the relay, and then returns to input mode for button monitoring.
    """

    def __init__(self, notification_service: NotificationService):
        self.notification_service = notification_service
        self._gpio_available = self._check_gpio_available()

        # Button monitoring state
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop_event = threading.Event()
        self._monitored_doors: Dict[int, Door] = {}  # gpio_pin -> Door
        self._pin_locks: Dict[int, threading.Lock] = {}  # gpio_pin -> Lock
        self._last_button_press: Dict[int, float] = {}  # gpio_pin -> timestamp
        self._pin_in_output_mode: Dict[int, bool] = {}  # gpio_pin -> is_output
        self._pin_released_events: Dict[int, threading.Event] = {}  # gpio_pin -> Event

        # Last door event tracking
        self._last_door_event: Optional[LastDoorEvent] = None
        self._last_door_event_lock = threading.Lock()

    def _persist_door_event(
        self,
        door_id: int,
        event_type: DoorEventType,
        username: Optional[str] = None,
    ) -> None:
        """Persist a door event to the database."""
        # Import here to avoid circular import
        from app.dependencies import create_services_for_thread

        try:
            with create_services_for_thread() as services:
                services.door_events.create(
                    door_id=door_id,
                    event_type=event_type,
                    username=username,
                )
        except Exception as e:
            logger.error(f"Failed to persist door event: {e}")

    def get_last_door_event(self) -> Optional[dict]:
        """Get the last door event information."""
        with self._last_door_event_lock:
            if self._last_door_event:
                return {
                    "door_name": self._last_door_event.door_name,
                    "door_id": self._last_door_event.door_id,
                    "gpio_pin": self._last_door_event.gpio_pin,
                    "event_type": self._last_door_event.event_type.value,  # Convert enum to string
                    "username": self._last_door_event.username,
                    "timestamp": self._last_door_event.timestamp,
                }
            return None

    def _record_door_event(
        self,
        door: Door,
        event_type: DoorEventType,
        username: Optional[str] = None,
    ) -> None:
        """Record a door event."""
        with self._last_door_event_lock:
            self._last_door_event = LastDoorEvent(
                door_name=door.name,
                door_id=door.id,
                gpio_pin=door.gpio_pin,
                event_type=event_type,
                username=username,
                timestamp=datetime.now(),
            )

    def _check_gpio_available(self) -> bool:
        """Check if gpiod is available."""
        try:
            import gpiod  # noqa: F401

            return True
        except ImportError:
            logger.warning("gpiod not available, GPIO operations will be simulated")
            return False

    def start_button_monitoring(self, doors: List[Door]) -> None:
        """Start monitoring buttons for the given doors.

        Args:
            doors: List of Door objects to monitor for button presses.
        """
        if not settings.BUTTON_MONITOR_ENABLED:
            logger.info("Button monitoring is disabled by configuration")
            return

        if self._monitor_thread and self._monitor_thread.is_alive():
            logger.warning("Button monitoring already running")
            return

        # Register doors for monitoring
        for door in doors:
            self._monitored_doors[door.gpio_pin] = door
            self._pin_locks[door.gpio_pin] = threading.Lock()
            self._last_button_press[door.gpio_pin] = 0
            self._pin_in_output_mode[door.gpio_pin] = False
            self._pin_released_events[door.gpio_pin] = threading.Event()
            self._pin_released_events[door.gpio_pin].set()  # Initially released

        if not self._monitored_doors:
            logger.info("No doors to monitor for button presses")
            return

        self._monitor_stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._button_monitor_loop,
            name="button_monitor",
            daemon=True,
        )
        self._monitor_thread.start()
        logger.info(f"Button monitoring started for {len(self._monitored_doors)} doors")

    def stop_button_monitoring(self) -> None:
        """Stop the button monitoring thread."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_stop_event.set()
            self._monitor_thread.join(timeout=2.0)
            logger.info("Button monitoring stopped")
        self._monitored_doors.clear()
        self._pin_locks.clear()

    def update_monitored_doors(self, doors: List[Door]) -> None:
        """Update the list of monitored doors (e.g., after database changes)."""
        new_pins = {door.gpio_pin for door in doors}
        old_pins = set(self._monitored_doors.keys())

        # Remove doors no longer in list
        for pin in old_pins - new_pins:
            del self._monitored_doors[pin]
            del self._pin_locks[pin]
            if pin in self._last_button_press:
                del self._last_button_press[pin]
            if pin in self._pin_in_output_mode:
                del self._pin_in_output_mode[pin]
            if pin in self._pin_released_events:
                del self._pin_released_events[pin]

        # Add new doors
        for door in doors:
            if door.gpio_pin not in self._monitored_doors:
                self._monitored_doors[door.gpio_pin] = door
                self._pin_locks[door.gpio_pin] = threading.Lock()
                self._last_button_press[door.gpio_pin] = 0
                self._pin_in_output_mode[door.gpio_pin] = False
                self._pin_released_events[door.gpio_pin] = threading.Event()
                self._pin_released_events[door.gpio_pin].set()  # Initially released
            else:
                # Update existing door info
                self._monitored_doors[door.gpio_pin] = door

    def _button_monitor_loop(self) -> None:
        """Main loop for monitoring button presses on GPIO pins using edge events."""
        if not self._gpio_available:
            logger.info(
                "GPIO not available, button monitoring running in simulation mode"
            )
            # In simulation mode, just keep the thread alive but don't do anything
            while not self._monitor_stop_event.is_set():
                self._monitor_stop_event.wait(timeout=1.0)
            return

        import gpiod
        from gpiod.line import Direction, Bias, Edge

        chip_path = "/dev/gpiochip0"

        logger.info("Button monitor loop starting with edge detection...")

        while not self._monitor_stop_event.is_set():
            # Get current pins to monitor (excluding those in output mode)
            pins_to_monitor = {
                pin: door
                for pin, door in self._monitored_doors.items()
                if not self._pin_in_output_mode.get(pin, False)
            }

            if not pins_to_monitor:
                # No pins to monitor, wait and retry
                self._monitor_stop_event.wait(timeout=0.5)
                continue

            try:
                # Configure all pins for edge detection with pull-up
                config = {
                    pin: gpiod.LineSettings(
                        direction=Direction.INPUT,
                        bias=Bias.PULL_UP,
                        edge_detection=Edge.FALLING,  # Detect button press (high->low)
                    )
                    for pin in pins_to_monitor.keys()
                }

                with gpiod.request_lines(
                    chip_path,
                    consumer="usbutler-button",
                    config=config,
                ) as request:
                    # Clear released events for pins we're now holding
                    for pin in pins_to_monitor:
                        event = self._pin_released_events.get(pin)
                        if event:
                            event.clear()

                    # Wait for events with timeout so we can check for stop signal
                    # and re-evaluate which pins to monitor
                    while not self._monitor_stop_event.is_set():
                        # Check if any pin switched to output mode
                        if any(
                            self._pin_in_output_mode.get(pin, False)
                            for pin in pins_to_monitor
                        ):
                            # Need to release and re-request with updated pin list
                            break

                        # Wait for edge event with timeout
                        if request.wait_edge_events(timeout=0.5):
                            for event in request.read_edge_events():
                                gpio_pin = event.line_offset
                                door = pins_to_monitor.get(gpio_pin)

                                if not door:
                                    continue

                                # Skip if pin is now in output mode
                                if self._pin_in_output_mode.get(gpio_pin, False):
                                    continue

                                current_time = time.time()
                                last_press = self._last_button_press.get(gpio_pin, 0)

                                # Debounce: only trigger if enough time has passed
                                if (
                                    current_time - last_press
                                    > settings.BUTTON_DEBOUNCE_TIME
                                ):
                                    self._last_button_press[gpio_pin] = current_time
                                    logger.info(
                                        f"Button press detected on GPIO {gpio_pin} "
                                        f"for door '{door.name}'"
                                    )
                                    # Record the event (in-memory)
                                    self._record_door_event(door, DoorEventType.BUTTON)
                                    # Persist to database
                                    _door_executor.submit(
                                        self._persist_door_event,
                                        door.id,
                                        DoorEventType.BUTTON,
                                        None,
                                    )
                                    # Send notification in a separate thread
                                    _door_executor.submit(
                                        self.notification_service.notify_button_pressed,
                                        door.name,
                                        gpio_pin,
                                    )

                # Lines released - signal waiting threads
                for pin in pins_to_monitor:
                    event = self._pin_released_events.get(pin)
                    if event:
                        event.set()

            except Exception as e:
                logger.error(f"Error in button monitor: {e}")
                # Signal release on error too
                for pin in pins_to_monitor:
                    event = self._pin_released_events.get(pin)
                    if event:
                        event.set()
                # Wait before retrying
                self._monitor_stop_event.wait(timeout=1.0)

        logger.info("Button monitor loop exiting")

    def _open_door_sync(
        self,
        door: Door,
        username: Optional[str] = None,
        event_type: DoorEventType = DoorEventType.API,
    ) -> bool:
        """
        Synchronously open a door using GPIO.

        This method:
        1. Acquires the pin lock to pause button monitoring
        2. Marks pin as in output mode
        3. Requests the GPIO line as output
        4. Sets it to active state
        5. Waits for the hold time
        6. Sets it to inactive state
        7. Releases the line
        8. Marks pin as back in input mode
        9. Releases the lock
        10. Sends notifications
        """
        logger.info(
            f"Opening door '{door.name}' (pin={door.gpio_pin}, "
            f"active_low={door.gpio_active_low}, hold_time={door.open_hold_time}s)"
        )

        success = False
        gpio_pin = door.gpio_pin
        lock = self._pin_locks.get(gpio_pin)
        released_event = self._pin_released_events.get(gpio_pin)

        try:
            # Acquire lock to pause button monitoring for this pin
            if lock:
                lock.acquire()

            # Signal that we need output mode and wait for button monitor to release
            self._pin_in_output_mode[gpio_pin] = True
            if released_event:
                # Wait for button monitor to release the pin (max 2 seconds)
                if not released_event.wait(timeout=2.0):
                    logger.warning(f"Timeout waiting for GPIO {gpio_pin} release")

            if self._gpio_available:
                success = self._control_gpio(door)
            else:
                success = self._simulate_gpio(door)

        except Exception as e:
            logger.error(f"Error controlling door '{door.name}': {e}")
            success = False
        finally:
            # Release lock and mark pin as back in input mode
            self._pin_in_output_mode[gpio_pin] = False
            if lock:
                lock.release()

        # Record the event
        if success:
            self._record_door_event(door, event_type, username)

        # Send notifications
        self.notification_service.notify_door_opened(
            door_name=door.name,
            username=username,
            success=success,
        )

        return success

    def _control_gpio(self, door: Door) -> bool:
        """Control the door using gpiod."""
        import gpiod
        from gpiod.line import Direction, Value

        # Determine active/inactive values based on active_low setting
        active_value = Value.INACTIVE if door.gpio_active_low else Value.ACTIVE
        inactive_value = Value.ACTIVE if door.gpio_active_low else Value.INACTIVE

        try:
            # Find the GPIO chip (usually /dev/gpiochip0 on Raspberry Pi)
            chip_path = "/dev/gpiochip0"

            with gpiod.request_lines(
                chip_path,
                consumer="usbutler-door",
                config={door.gpio_pin: gpiod.LineSettings(direction=Direction.OUTPUT)},
            ) as request:
                # Set to active state (open door)
                request.set_value(door.gpio_pin, active_value)
                logger.debug(f"GPIO {door.gpio_pin} set to active (output mode)")

                # Hold for specified time
                time.sleep(door.open_hold_time)

                # Set to inactive state (close door)
                request.set_value(door.gpio_pin, inactive_value)
                logger.debug(f"GPIO {door.gpio_pin} set to inactive")

            logger.info(f"Door '{door.name}' opened successfully")
            return True

        except Exception as e:
            logger.error(f"GPIO control error for door '{door.name}': {e}")
            return False

    def _simulate_gpio(self, door: Door) -> bool:
        """Simulate GPIO control when gpiod is not available."""
        logger.info(f"[SIMULATED] Setting GPIO {door.gpio_pin} to active (output mode)")
        time.sleep(door.open_hold_time)
        logger.info(f"[SIMULATED] Setting GPIO {door.gpio_pin} to inactive")
        return True

    def open_door(
        self,
        door: Door,
        username: Optional[str] = None,
        event_type: DoorEventType = DoorEventType.API,
    ) -> bool:
        """
        Open a door asynchronously (non-blocking for the web server).

        Submits the door opening operation to a thread pool and returns immediately.
        """
        future = _door_executor.submit(self._open_door_sync, door, username, event_type)
        # We don't wait for the result here to keep it non-blocking
        # The future will complete in the background
        logger.info(f"Door open request submitted for '{door.name}'")
        return True

    def open_door_blocking(
        self,
        door: Door,
        username: Optional[str] = None,
        event_type: DoorEventType = DoorEventType.API,
    ) -> bool:
        """
        Open a door synchronously (blocking).

        Use this when you need to wait for the operation to complete.
        """
        return self._open_door_sync(door, username, event_type)

    def open_door_for_card(
        self,
        door: Door,
        username: Optional[str] = None,
    ) -> bool:
        """
        Open a door for a card scan (non-blocking).

        This is a convenience method that sets the event type to CARD.
        """
        return self.open_door(door, username, DoorEventType.CARD)

    async def open_door_async(
        self,
        door: Door,
        username: Optional[str] = None,
        event_type: DoorEventType = DoorEventType.API,
    ) -> bool:
        """
        Open a door asynchronously using asyncio.

        This is the preferred method for use in async contexts like FastAPI endpoints.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _door_executor,
            self._open_door_sync,
            door,
            username,
            event_type,
        )
