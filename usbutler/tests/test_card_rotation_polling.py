"""Integration of authorization, door actuation, and best-effort rotation."""

from contextlib import contextmanager
from types import SimpleNamespace

from app.models.door import Door
from app.models.identifier import IdentifierType
from app.routers.ui import templates
from app.schemas.identifier import IdentifierCreate
from app.schemas.user import UserCreate
from app.services.card_reader import CardScanResult
from app.services.card_reader_polling import CardReaderPollingService
from app.services.door_service import DoorService
from app.services.identifier_service import IdentifierService
from app.services.uid_rotation_service import UidRotationService
from app.services.user_service import UserService


class FakeDoorControl:
    def __init__(self, events):
        self.events = events

    def open_door_async(self, *args, **kwargs):
        self.events.append("open")
        return True


class ExplodingWriter:
    def __init__(self, events):
        self.events = events

    def write_uid(self, source_uid, target_uid):
        self.events.append("write")
        raise RuntimeError("reader disconnected")


class UnusedReaderService:
    nfc_reader = SimpleNamespace()


def test_rotation_failure_does_not_block_door(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.uid_rotation_service.secrets.token_bytes",
        lambda _: bytes.fromhex("11111111"),
    )
    users = UserService(db)
    identifiers = IdentifierService(db)
    doors = DoorService(db)
    user = users.create(UserCreate(username="alice"))
    identifiers.create(
        IdentifierCreate(value="01020304", type=IdentifierType.UID, user_id=user.id)
    )
    door = Door(name="Front", gpio_pin=17, open_hold_time=0.01)
    db.add(door)
    db.commit()

    @contextmanager
    def services():
        yield SimpleNamespace(
            db=db,
            users=users,
            identifiers=identifiers,
            doors=doors,
        )

    events = []
    polling = CardReaderPollingService(
        card_reader_service=UnusedReaderService(),
        door_control_service=FakeDoorControl(events),
        session_factory=services,
        uid_writer=ExplodingWriter(events),
    )
    scan = CardScanResult(
        uid="01020304",
        atr="3B8F8001804F0CA000000306030001",
        mifare_classic=True,
        identifiers={"identifier": {"type": "UID", "value": "01020304"}},
    )

    polling._authenticate("01020304", scan)

    assert events == ["open", "write"]
    lineage = UidRotationService(db).get_lineage(1)
    assert lineage["attempts"][0].outcome.value == "connection_loss"


def test_admin_ui_renders_masked_lineage_and_last_attempt(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.uid_rotation_service.secrets.token_bytes",
        lambda _: bytes.fromhex("11111111"),
    )
    users = UserService(db)
    user = users.create(UserCreate(username="alice"))
    root = IdentifierService(db).create(
        IdentifierCreate(value="01020304", type=IdentifierType.UID, user_id=user.id)
    )
    rotation = UidRotationService(db)
    rotation.prepare_write(root.id)
    lineage = rotation.get_lineage(root.id)

    html = templates.env.get_template("index.html").render(
        users=users.get_all(),
        lineages={root.id: lineage},
        last_scan=None,
        last_scan_identifier=None,
        auth_enabled=False,
    )

    assert "01..04" in html
    assert "11..11" in html
    assert "unknown · started" in html
    assert "01020304" not in html
