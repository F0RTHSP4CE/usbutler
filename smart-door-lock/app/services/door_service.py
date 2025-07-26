"""
Door Control Service - Handles physical door lock operations.
Separated from authentication logic for better modularity.
"""

import time
from typing import Optional
from app.services.auth_service import User


class DoorEvent:
    """Door event data model"""

    def __init__(self, user: User, event_type: str, timestamp: Optional[float] = None):
        self.user = user
        self.event_type = event_type  # 'open', 'close', 'auto_lock'
        self.timestamp = timestamp or time.time()


class DoorControlService:
    """Service for controlling the smart door lock"""

    def __init__(self, auto_lock_delay: int = 5):
        self.is_open = False
        self.auto_lock_delay = auto_lock_delay
        self.last_user: Optional[User] = None
        self.event_history = []

    def open_door(self, user: User) -> DoorEvent:
        """
        Open the door for an authenticated user
        Returns DoorEvent for logging/audit purposes
        """
        print(f"🔓 DOOR OPENED for {user.name} ({user.access_level})")
        self.is_open = True
        self.last_user = user

        event = DoorEvent(user, "open")
        self.event_history.append(event)

        # Schedule auto-lock
        self._schedule_auto_lock()

        return event

    def lock_door(self, user: Optional[User] = None) -> DoorEvent:
        """
        Lock the door manually
        Returns DoorEvent for logging/audit purposes
        """
        print("🔒 DOOR LOCKED")
        self.is_open = False

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

    def set_auto_lock_delay(self, delay: int):
        """Set the auto-lock delay in seconds"""
        self.auto_lock_delay = delay

    def _schedule_auto_lock(self):
        """Schedule automatic door locking after delay"""
        if self.auto_lock_delay > 0:
            print(f"Door will auto-lock in {self.auto_lock_delay} seconds...")
            # Note: In production, this should use threading or async
            # For now, we'll do synchronous sleep but make it interruptible
            import threading

            def auto_lock():
                import time

                time.sleep(self.auto_lock_delay)
                if (
                    self.is_open
                ):  # Check if still open (user might have manually locked)
                    self.lock_door()

            # Run auto-lock in a separate thread so it doesn't block
            thread = threading.Thread(target=auto_lock, daemon=True)
            thread.start()
