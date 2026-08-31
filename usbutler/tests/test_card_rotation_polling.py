"""Integration of authorization, door actuation, and best-effort rotation."""

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

from app.models.door import Door
from app.models.identifier import IdentifierType, MifareUuidState, MifareUuidValue
from app.routers.ui import templates
from app.schemas.identifier import IdentifierCreate
from app.schemas.user import UserCreate, UserUpdate
from app.models.user import UserStatus
from app.services.card_reader import CardReaderService, CardScanResult
from app.services.card_reader_polling import CardReaderPollingService
from app.services.door_service import DoorService
from app.services.identifier_service import IdentifierService
from app.services.mifare_block import MifareWriteResult
from app.services.mifare_rotation_service import MifareRotationService
from app.services.user_service import UserService


class FakeDoorControl:
    def __init__(self, events):
        self.events = events

    def open_door_async(self, *args, **kwargs):
        self.events.append("open")
        return True


class FakeNotifications:
    def __init__(self, events=None):
        self.events = events
        self.messages = []

    def notify_security_alert_async(self, message):
        if self.events is not None:
            self.events.append("notify")
        self.messages.append(message)


class FakeMifareStore:
    def __init__(self, events, verified):
        self.events = events
        self.verified = verified
        self.targets = []

    def read_uuid(self):
        return None

    def write_and_verify(self, target, expected_uid=None):
        self.events.append("write")
        self.targets.append(target)
        return MifareWriteResult(
            verified=self.verified,
            attempts=1,
            observed_uuid=target if self.verified else None,
            detail=None if self.verified else "card removed",
        )


class UnusedReaderService:
    nfc_reader = SimpleNamespace()
    mifare_store = None


def setup_access(db, enabled=True):
    users = UserService(db)
    identifiers = IdentifierService(db)
    doors = DoorService(db)
    user = users.create(UserCreate(username="alice", mifare_rotation_enabled=enabled))
    identifier = identifiers.create(
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

    return user, identifier, services


def scan(data_uuid=None):
    return CardScanResult(
        uid="01020304",
        atr="3B8F8001804F0CA000000306030001",
        mifare_classic=True,
        mifare_uuid=data_uuid,
        identifiers={"identifier": {"type": "UID", "value": "01020304"}},
    )


def test_failed_rewrite_never_blocks_door_and_reuses_pending(db):
    _, _, services = setup_access(db)
    events = []
    store = FakeMifareStore(events, verified=False)
    polling = CardReaderPollingService(
        card_reader_service=UnusedReaderService(),
        door_control_service=FakeDoorControl(events),
        session_factory=services,
        mifare_store=store,
    )

    polling._authenticate(scan())
    polling._authenticate(scan())

    assert events == ["open", "write", "open", "write"]
    assert store.targets[0] == store.targets[1]
    values = db.query(MifareUuidValue).all()
    assert len(values) == 1
    assert values[0].state == MifareUuidState.PENDING


def test_verified_rewrite_is_confirmed_after_door_submission(db):
    _, identifier, services = setup_access(db)
    events = []
    store = FakeMifareStore(events, verified=True)
    polling = CardReaderPollingService(
        card_reader_service=UnusedReaderService(),
        door_control_service=FakeDoorControl(events),
        session_factory=services,
        mifare_store=store,
    )

    polling._authenticate(scan())

    assert events == ["open", "write"]
    value = db.query(MifareUuidValue).one()
    assert value.state == MifareUuidState.CONFIRMED
    assert identifier.mifare_credential.last_verified_rotation_at is not None
    assert identifier.last_used_at is not None


def test_later_scan_of_pending_target_confirms_without_another_write(db):
    _, identifier, services = setup_access(db)
    prepared = MifareRotationService(db).prepare_write(identifier.id)
    events = []
    store = FakeMifareStore(events, verified=True)
    polling = CardReaderPollingService(
        card_reader_service=UnusedReaderService(),
        door_control_service=FakeDoorControl(events),
        session_factory=services,
        mifare_store=store,
    )

    polling._authenticate(scan(data_uuid=prepared.target_uuid))

    assert events == ["open"]
    assert db.query(MifareUuidValue).one().state == MifareUuidState.CONFIRMED


def test_disabled_user_keeps_access_but_performs_no_write(db):
    _, _, services = setup_access(db, enabled=False)
    events = []
    polling = CardReaderPollingService(
        card_reader_service=UnusedReaderService(),
        door_control_service=FakeDoorControl(events),
        session_factory=services,
        mifare_store=FakeMifareStore(events, verified=True),
    )

    polling._authenticate(scan())

    assert events == ["open"]
    assert db.query(MifareUuidValue).count() == 0


def test_global_kill_switch_stops_writes_without_blocking_access(db, monkeypatch):
    _, _, services = setup_access(db, enabled=True)
    monkeypatch.setattr(
        "app.services.card_reader_polling.settings.MIFARE_DATA_ROTATION_ENABLED",
        False,
    )
    events = []
    polling = CardReaderPollingService(
        card_reader_service=UnusedReaderService(),
        door_control_service=FakeDoorControl(events),
        session_factory=services,
        mifare_store=FakeMifareStore(events, verified=True),
    )

    polling._authenticate(scan())

    assert events == ["open"]
    assert db.query(MifareUuidValue).count() == 0


def test_last_used_persistence_failure_does_not_block_access(db, monkeypatch):
    _, identifier, services = setup_access(db, enabled=False)

    def fail_mark_used(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(IdentifierService, "mark_used", fail_mark_used)
    events = []
    polling = CardReaderPollingService(
        card_reader_service=UnusedReaderService(),
        door_control_service=FakeDoorControl(events),
        session_factory=services,
    )

    polling._authenticate(scan())

    assert events == ["open"]
    assert identifier.last_used_at is None


def test_unknown_card_sends_masked_security_notification(db):
    _, _, services = setup_access(db)
    events = []
    notifications = FakeNotifications(events)
    polling = CardReaderPollingService(
        card_reader_service=UnusedReaderService(),
        door_control_service=FakeDoorControl(events),
        session_factory=services,
        notification_service=notifications,
    )

    polling._authenticate(
        CardScanResult(
            uid="DEADBEEF",
            mifare_classic=True,
            identifiers={"identifier": {"type": "UID", "value": "DEADBEEF"}},
        )
    )

    assert events == ["notify"]
    assert notifications.messages == ["⚠️ Unknown card · DENIED · DE..EF · unknown"]


def test_disabled_user_sends_notification_and_does_not_open(db):
    user, _, services = setup_access(db)
    UserService(db).update(user.id, UserUpdate(status=UserStatus.INACTIVE))
    events = []
    notifications = FakeNotifications(events)
    polling = CardReaderPollingService(
        card_reader_service=UnusedReaderService(),
        door_control_service=FakeDoorControl(events),
        session_factory=services,
        notification_service=notifications,
    )

    polling._authenticate(scan())

    assert events == ["notify"]
    assert notifications.messages == ["⚠️ Disabled user · DENIED · 01..04 · alice"]


def test_enrolled_card_with_wrong_uuid_sends_notification(db):
    _, identifier, services = setup_access(db)
    rotation = MifareRotationService(db)
    prepared = rotation.prepare_write(identifier.id)
    rotation.confirm_observed(identifier.id, prepared.target_uuid, 3)
    wrong_uuid = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    notifications = FakeNotifications()
    events = []
    polling = CardReaderPollingService(
        card_reader_service=UnusedReaderService(),
        door_control_service=FakeDoorControl(events),
        session_factory=services,
        notification_service=notifications,
    )

    polling._authenticate(scan(data_uuid=wrong_uuid))

    assert events == []
    assert notifications.messages == ["⚠️ Wrong/missing UUID · DENIED · 01..04 · alice"]
    assert wrong_uuid not in notifications.messages[0]
    assert identifier.last_used_at is None


def test_granted_uid_uuid_owner_mismatch_does_not_notify(db):
    _, identifier, services = setup_access(db)
    users = UserService(db)
    identifiers = IdentifierService(db)
    bob = users.create(UserCreate(username="bob"))
    identifiers.create(
        IdentifierCreate(value="DEADBEEF", type=IdentifierType.UID, user_id=bob.id)
    )
    rotation = MifareRotationService(db)
    prepared = rotation.prepare_write(identifier.id)
    rotation.confirm_observed(identifier.id, prepared.target_uuid, 3)
    events = []
    notifications = FakeNotifications(events)
    polling = CardReaderPollingService(
        card_reader_service=UnusedReaderService(),
        door_control_service=FakeDoorControl(events),
        session_factory=services,
        notification_service=notifications,
    )
    mismatched_scan = scan(data_uuid=prepared.target_uuid)
    mismatched_scan.uid = "DEADBEEF"
    mismatched_scan.identifiers["identifier"]["value"] = "DEADBEEF"

    polling._authenticate(mismatched_scan)

    assert events == ["open"]
    assert notifications.messages == []


def test_admin_ui_has_opt_in_checkbox_without_raw_uuid_history(db):
    _, identifier, _ = setup_access(db, enabled=True)
    prepared = MifareRotationService(db).prepare_write(identifier.id)
    MifareRotationService(db).confirm_observed(identifier.id, prepared.target_uuid, 3)
    IdentifierService(db).mark_used(identifier.id, datetime(2026, 8, 31, 12, 34))

    html = templates.env.get_template("index.html").render(
        users=UserService(db).get_all(),
        rolling_all_enabled=True,
        last_scan=None,
        last_scan_identifier=None,
        auth_enabled=False,
    )

    assert "MIFARE Rotation" in html
    assert "mifare_rotation_enabled" in html
    assert "checked" in html
    assert "Disable rolling for all users" in html
    assert "/users/mifare-rotation/all" in html
    assert "mifare-enrolled" in html
    assert "enrolled · 1 accepted UUID" in html
    assert "Last used: 2026-08-31 12:34 UTC" in html
    assert prepared.target_uuid not in html


def test_admin_ui_grays_out_inactive_user_row(db):
    user, _, _ = setup_access(db)
    UserService(db).update(user.id, UserUpdate(status=UserStatus.INACTIVE))

    html = templates.env.get_template("index.html").render(
        users=UserService(db).get_all(),
        rolling_all_enabled=False,
        last_scan=None,
        last_scan_identifier=None,
        auth_enabled=False,
    )

    assert '<tr class="user-inactive">' in html


class PollingReader:
    def __init__(self, result):
        self.nfc_reader = SimpleNamespace()
        self.mifare_store = None
        self.result = result
        self.removal_waits = 0
        self.disconnects = 0

    def wait_for_card(self, timeout=5):
        return True

    def read_card_data(self):
        return self.result

    def wait_for_card_removal(self, timeout=2):
        self.removal_waits += 1
        return True

    def disconnect(self):
        self.disconnects += 1


def test_successful_scan_does_not_restart_pcscd():
    reader = PollingReader(scan())
    polling = CardReaderPollingService(
        card_reader_service=reader,
        door_control_service=SimpleNamespace(),
        session_factory=lambda: None,
    )
    authenticated = []
    restarts = []
    polling._authenticate = lambda result: authenticated.append(result.uid)
    polling._restart_pcscd = lambda: restarts.append(True)

    polling._poll_once()

    assert authenticated == ["01020304"]
    assert restarts == []
    assert reader.removal_waits == 1
    assert reader.disconnects == 1


def test_known_mifare_uuid_can_reach_auth_when_uid_read_failed():
    uuid_only = scan(data_uuid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    uuid_only.uid = None
    uuid_only.identifiers = {}
    reader = PollingReader(uuid_only)
    polling = CardReaderPollingService(
        card_reader_service=reader,
        door_control_service=SimpleNamespace(),
        session_factory=lambda: None,
    )
    authenticated = []
    polling._authenticate = lambda result: authenticated.append(result.mifare_uuid)

    polling._poll_once()

    assert authenticated == ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"]
    assert polling.get_last_scan() is None


def test_pcscd_restarts_only_after_three_failed_identifier_reads():
    reader = PollingReader(CardScanResult())
    polling = CardReaderPollingService(
        card_reader_service=reader,
        door_control_service=SimpleNamespace(),
        session_factory=lambda: None,
    )
    restarts = []
    polling._restart_pcscd = lambda: restarts.append(True)

    polling._poll_once()
    polling._poll_once()
    assert restarts == []
    polling._poll_once()

    assert restarts == [True]
    assert reader.removal_waits == 0


class RetryingUidReader:
    connection = SimpleNamespace()

    def __init__(self):
        self.calls = 0

    def is_connected(self):
        return True

    def send_apdu(self, command):
        self.calls += 1
        if self.calls == 1:
            return [], 0x63, 0x00
        return [0x01, 0x02, 0x03, 0x04], 0x90, 0x00


def test_uid_read_retries_a_transient_status_failure():
    reader = RetryingUidReader()
    assert CardReaderService(reader)._get_uid() == "01020304"
    assert reader.calls == 2
