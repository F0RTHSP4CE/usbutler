import pytest
from fastapi import HTTPException

from schemas import (
    UserCreate,
    UserUpdate,
    UserStatus,
    IdentifierCreate,
    IdentifierUpdate,
    IdentifierType,
    DoorCreate,
    DoorUpdate,
    GpioSettings,
)
from services import UserService, IdentifierService, DoorService


class TestUserService:
    """Tests for UserService."""

    @pytest.fixture
    def service(self, db):
        return UserService(db)

    def test_create_user(self, service):
        """Test creating a user."""
        user_data = UserCreate(username="testuser", status=UserStatus.ACTIVE)
        user = service.create(user_data)

        assert user.username == "testuser"
        assert user.status == UserStatus.ACTIVE
        assert user.id is not None
        assert user.identifiers == []

    def test_create_duplicate_username(self, service):
        """Test creating a user with duplicate username fails."""
        user_data = UserCreate(username="testuser")
        service.create(user_data)

        with pytest.raises(HTTPException) as exc_info:
            service.create(user_data)
        assert exc_info.value.status_code == 400
        assert "already exists" in str(exc_info.value.detail)

    def test_get_by_id(self, service):
        """Test getting a user by ID."""
        user_data = UserCreate(username="testuser")
        created = service.create(user_data)

        user = service.get_by_id(created.id)
        assert user.username == "testuser"

    def test_get_by_id_not_found(self, service):
        """Test getting a nonexistent user raises 404."""
        with pytest.raises(HTTPException) as exc_info:
            service.get_by_id("nonexistent")
        assert exc_info.value.status_code == 404

    def test_get_all(self, service):
        """Test getting all users."""
        service.create(UserCreate(username="user1"))
        service.create(UserCreate(username="user2"))

        users = service.get_all()
        assert len(users) == 2

    def test_update_user(self, service):
        """Test updating a user."""
        user_data = UserCreate(username="testuser")
        created = service.create(user_data)

        update_data = UserUpdate(username="updated", status=UserStatus.DISABLED)
        updated = service.update(created.id, update_data)

        assert updated.username == "updated"
        assert updated.status == UserStatus.DISABLED

    def test_update_partial(self, service):
        """Test partial user update."""
        user_data = UserCreate(username="testuser", status=UserStatus.ACTIVE)
        created = service.create(user_data)

        update_data = UserUpdate(status=UserStatus.DISABLED)
        updated = service.update(created.id, update_data)

        assert updated.username == "testuser"  # Unchanged
        assert updated.status == UserStatus.DISABLED

    def test_delete_user(self, service):
        """Test deleting a user."""
        user_data = UserCreate(username="testuser")
        created = service.create(user_data)

        result = service.delete(created.id)
        assert result is True

        with pytest.raises(HTTPException):
            service.get_by_id(created.id)

    def test_add_identifier(self, service):
        """Test adding an identifier to a user."""
        user = service.create(UserCreate(username="testuser"))

        updated = service.add_identifier(user.id, "identifier-123")
        assert "identifier-123" in updated.identifiers

    def test_remove_identifier(self, service):
        """Test removing an identifier from a user."""
        user = service.create(UserCreate(username="testuser"))
        service.add_identifier(user.id, "identifier-123")

        updated = service.remove_identifier(user.id, "identifier-123")
        assert "identifier-123" not in updated.identifiers


class TestIdentifierService:
    """Tests for IdentifierService."""

    @pytest.fixture
    def service(self, db):
        return IdentifierService(db)

    def test_create_identifier(self, service):
        """Test creating an identifier."""
        identifier_data = IdentifierCreate(
            value="04:AA:BB:CC:DD:EE:FF",
            type=IdentifierType.UID,
            metadata={"source": "nfc_reader"},
        )
        identifier = service.create(identifier_data)

        assert identifier.value == "04:AA:BB:CC:DD:EE:FF"
        assert identifier.type == IdentifierType.UID
        assert identifier.owner_id is None
        assert identifier.metadata == {"source": "nfc_reader"}

    def test_create_identifier_with_owner(self, service):
        """Test creating an identifier with owner."""
        identifier_data = IdentifierCreate(
            value="1234567890123456", type=IdentifierType.PAN, owner_id="user-123"
        )
        identifier = service.create(identifier_data)

        assert identifier.owner_id == "user-123"

    def test_create_duplicate_value(self, service):
        """Test creating identifier with duplicate value fails."""
        identifier_data = IdentifierCreate(value="test-value", type=IdentifierType.UID)
        service.create(identifier_data)

        with pytest.raises(HTTPException) as exc_info:
            service.create(identifier_data)
        assert exc_info.value.status_code == 400

    def test_get_by_value(self, service):
        """Test getting identifier by value."""
        identifier_data = IdentifierCreate(
            value="unique-value", type=IdentifierType.UID
        )
        service.create(identifier_data)

        result = service.get_by_value("unique-value")
        assert result is not None
        assert result.value == "unique-value"

    def test_get_by_owner(self, service):
        """Test getting identifiers by owner."""
        service.create(
            IdentifierCreate(value="id1", type=IdentifierType.UID, owner_id="user1")
        )
        service.create(
            IdentifierCreate(value="id2", type=IdentifierType.PAN, owner_id="user1")
        )
        service.create(
            IdentifierCreate(value="id3", type=IdentifierType.UID, owner_id="user2")
        )

        user1_ids = service.get_by_owner("user1")
        assert len(user1_ids) == 2

    def test_assign_owner(self, service):
        """Test assigning owner to identifier."""
        identifier = service.create(
            IdentifierCreate(value="test", type=IdentifierType.UID)
        )

        updated = service.assign_owner(identifier.id, "new-owner")
        assert updated.owner_id == "new-owner"

    def test_unassign_owner(self, service):
        """Test unassigning owner from identifier."""
        identifier = service.create(
            IdentifierCreate(value="test", type=IdentifierType.UID, owner_id="owner")
        )

        updated = service.assign_owner(identifier.id, None)
        assert updated.owner_id is None


class TestDoorService:
    """Tests for DoorService."""

    @pytest.fixture
    def service(self, db):
        return DoorService(db)

    def test_create_door(self, service):
        """Test creating a door."""
        gpio = GpioSettings(pin=17, default_state=False, inverted=False, pull_up=True)
        door_data = DoorCreate(name="Front Door", gpio_settings=gpio)
        door = service.create(door_data)

        assert door.name == "Front Door"
        assert door.gpio_settings.pin == 17
        assert door.gpio_settings.pull_up is True

    def test_create_duplicate_name(self, service):
        """Test creating door with duplicate name fails."""
        gpio = GpioSettings(pin=17)
        door_data = DoorCreate(name="Front Door", gpio_settings=gpio)
        service.create(door_data)

        gpio2 = GpioSettings(pin=18)
        door_data2 = DoorCreate(name="Front Door", gpio_settings=gpio2)

        with pytest.raises(HTTPException) as exc_info:
            service.create(door_data2)
        assert exc_info.value.status_code == 400
        assert "name" in str(exc_info.value.detail).lower()

    def test_create_duplicate_gpio_pin(self, service):
        """Test creating door with duplicate GPIO pin fails."""
        gpio = GpioSettings(pin=17)
        door_data = DoorCreate(name="Front Door", gpio_settings=gpio)
        service.create(door_data)

        door_data2 = DoorCreate(name="Back Door", gpio_settings=gpio)

        with pytest.raises(HTTPException) as exc_info:
            service.create(door_data2)
        assert exc_info.value.status_code == 400
        assert "pin" in str(exc_info.value.detail).lower()

    def test_get_by_name(self, service):
        """Test getting door by name."""
        gpio = GpioSettings(pin=17)
        service.create(DoorCreate(name="Test Door", gpio_settings=gpio))

        door = service.get_by_name("Test Door")
        assert door is not None
        assert door.name == "Test Door"

    def test_get_by_gpio_pin(self, service):
        """Test getting door by GPIO pin."""
        gpio = GpioSettings(pin=22)
        service.create(DoorCreate(name="Test Door", gpio_settings=gpio))

        door = service.get_by_gpio_pin(22)
        assert door is not None
        assert door.gpio_settings.pin == 22

    def test_update_door(self, service):
        """Test updating a door."""
        gpio = GpioSettings(pin=17)
        door = service.create(DoorCreate(name="Old Name", gpio_settings=gpio))

        new_gpio = GpioSettings(pin=18, inverted=True)
        update_data = DoorUpdate(name="New Name", gpio_settings=new_gpio)
        updated = service.update(door.id, update_data)

        assert updated.name == "New Name"
        assert updated.gpio_settings.pin == 18
        assert updated.gpio_settings.inverted is True

    def test_delete_door(self, service):
        """Test deleting a door."""
        gpio = GpioSettings(pin=17)
        door = service.create(DoorCreate(name="Test Door", gpio_settings=gpio))

        result = service.delete(door.id)
        assert result is True

        with pytest.raises(HTTPException):
            service.get_by_id(door.id)
