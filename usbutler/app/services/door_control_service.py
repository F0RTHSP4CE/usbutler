"""Door control service for GPIO operations."""

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.models.door import Door
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

# Thread pool for non-blocking door operations
_door_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="door_control_")


class DoorControlService:
    """Service for controlling physical doors via GPIO."""

    def __init__(self, notification_service: Optional[NotificationService] = None):
        self.notification_service = notification_service or NotificationService()
        self._gpio_available = self._check_gpio_available()

    def _check_gpio_available(self) -> bool:
        """Check if gpiod is available."""
        try:
            import gpiod  # noqa: F401

            return True
        except ImportError:
            logger.warning("gpiod not available, GPIO operations will be simulated")
            return False

    def _open_door_sync(
        self,
        door: Door,
        username: Optional[str] = None,
    ) -> bool:
        """
        Synchronously open a door using GPIO.

        This method:
        1. Requests the GPIO line
        2. Sets it to active state
        3. Waits for the hold time
        4. Sets it to inactive state
        5. Releases the line
        6. Sends notifications
        """
        logger.info(
            f"Opening door '{door.name}' (pin={door.gpio_pin}, "
            f"active_low={door.gpio_active_low}, hold_time={door.open_hold_time}s)"
        )

        success = False
        try:
            if self._gpio_available:
                success = self._control_gpio(door)
            else:
                success = self._simulate_gpio(door)

        except Exception as e:
            logger.error(f"Error controlling door '{door.name}': {e}")
            success = False

        # Send notifications
        self.notification_service.notify_door_opened(
            door_name=door.name,
            username=username,
            success=success,
        )

        return success

    def _control_gpio(self, door: Door) -> bool:
        """Control the door using gpiod."""
        import time

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
                logger.debug(f"GPIO {door.gpio_pin} set to active")

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
        import time

        logger.info(f"[SIMULATED] Setting GPIO {door.gpio_pin} to active")
        time.sleep(door.open_hold_time)
        logger.info(f"[SIMULATED] Setting GPIO {door.gpio_pin} to inactive")
        return True

    def open_door(
        self,
        door: Door,
        username: Optional[str] = None,
    ) -> bool:
        """
        Open a door asynchronously (non-blocking for the web server).

        Submits the door opening operation to a thread pool and returns immediately.
        """
        future = _door_executor.submit(self._open_door_sync, door, username)
        # We don't wait for the result here to keep it non-blocking
        # The future will complete in the background
        logger.info(f"Door open request submitted for '{door.name}'")
        return True

    def open_door_blocking(
        self,
        door: Door,
        username: Optional[str] = None,
    ) -> bool:
        """
        Open a door synchronously (blocking).

        Use this when you need to wait for the operation to complete.
        """
        return self._open_door_sync(door, username)

    async def open_door_async(
        self,
        door: Door,
        username: Optional[str] = None,
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
        )
