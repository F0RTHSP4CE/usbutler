"""Door actuation tests, including database-session handoff."""

from concurrent.futures import Future

import pytest
from sqlalchemy.orm.exc import DetachedInstanceError

from app.models.door import Door
from app.models.door_event import DoorEventType
from app.services.door_control_service import DoorControlService, DoorSnapshot


class CapturingExecutor:
    def __init__(self):
        self.call = None

    def submit(self, function, *args):
        self.call = (function, args)
        return Future()


class NotificationRecorder:
    def __init__(self):
        self.calls = []

    def notify_door_opened_async(self, *args):
        self.calls.append(args)


def test_async_open_survives_caller_session_rollback(db, monkeypatch):
    """A queued door job must not retain an expirable SQLAlchemy model."""
    door = Door(
        name="Front",
        gpio_pin=17,
        gpio_active_low=True,
        open_hold_time=0.01,
    )
    db.add(door)
    db.commit()

    executor = CapturingExecutor()
    monkeypatch.setattr("app.services.door_control_service._executor", executor)
    notifications = NotificationRecorder()
    service = DoorControlService(notifications, lambda: None)
    service._gpio_available = False
    persisted = []
    monkeypatch.setattr(service, "_simulate_gpio", lambda snapshot: True)
    monkeypatch.setattr(
        service,
        "_persist_event",
        lambda *args: persisted.append(args),
    )

    service.open_door_async(
        door,
        "alice",
        DoorEventType.CARD,
        user_id=7,
    )
    door_id = door.id

    assert executor.call is not None
    function, args = executor.call
    assert isinstance(args[0], DoorSnapshot)

    # This mirrors a rotation transaction rolling back after door submission:
    # conditional update: rollback expires the session's ORM objects, then the
    # authentication context closes before the executor necessarily runs.
    db.rollback()
    db.expunge(door)
    with pytest.raises(DetachedInstanceError):
        _ = door.name

    assert function(*args) is True
    assert persisted == [(door_id, DoorEventType.CARD, "alice", 7, None)]
    assert notifications.calls == [("Front", "alice", True, None)]
