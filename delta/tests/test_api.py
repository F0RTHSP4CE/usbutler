import pytest
from fastapi import status


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_root(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "ok"

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "healthy"


class TestUsersAPI:
    """Tests for Users API endpoints."""

    def test_list_users_empty(self, client):
        """Test listing users when none exist."""
        response = client.get("/api/users")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["data"] == []
        assert data["total"] == 0

    def test_create_user(self, client, sample_user_data):
        """Test creating a user."""
        response = client.post("/api/users", json=sample_user_data)
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["success"] is True
        assert data["data"]["username"] == "testuser"
        assert data["data"]["status"] == "Active"
        assert "id" in data["data"]

    def test_create_user_disabled(self, client):
        """Test creating a disabled user."""
        response = client.post(
            "/api/users", json={"username": "disabled_user", "status": "Disabled"}
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["data"]["status"] == "Disabled"

    def test_create_user_duplicate(self, client, sample_user_data):
        """Test creating duplicate user fails."""
        client.post("/api/users", json=sample_user_data)
        response = client.post("/api/users", json=sample_user_data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_user(self, client, sample_user_data):
        """Test getting a user by ID."""
        create_response = client.post("/api/users", json=sample_user_data)
        user_id = create_response.json()["data"]["id"]

        response = client.get(f"/api/users/{user_id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["username"] == "testuser"

    def test_get_user_not_found(self, client):
        """Test getting nonexistent user."""
        response = client.get("/api/users/nonexistent-id")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_user(self, client, sample_user_data):
        """Test updating a user."""
        create_response = client.post("/api/users", json=sample_user_data)
        user_id = create_response.json()["data"]["id"]

        response = client.put(
            f"/api/users/{user_id}",
            json={"username": "updated_user", "status": "Disabled"},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]
        assert data["username"] == "updated_user"
        assert data["status"] == "Disabled"

    def test_delete_user(self, client, sample_user_data):
        """Test deleting a user."""
        create_response = client.post("/api/users", json=sample_user_data)
        user_id = create_response.json()["data"]["id"]

        response = client.delete(f"/api/users/{user_id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify deleted
        get_response = client.get(f"/api/users/{user_id}")
        assert get_response.status_code == status.HTTP_404_NOT_FOUND

    def test_list_users(self, client):
        """Test listing multiple users."""
        client.post("/api/users", json={"username": "user1"})
        client.post("/api/users", json={"username": "user2"})

        response = client.get("/api/users")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 2
        assert len(data["data"]) == 2


class TestIdentifiersAPI:
    """Tests for Identifiers API endpoints."""

    def test_list_identifiers_empty(self, client):
        """Test listing identifiers when none exist."""
        response = client.get("/api/identifiers")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"] == []

    def test_create_identifier_uid(self, client, sample_identifier_data):
        """Test creating a UID identifier."""
        response = client.post("/api/identifiers", json=sample_identifier_data)
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()["data"]
        assert data["value"] == "04:AA:BB:CC:DD:EE:FF"
        assert data["type"] == "UID"
        assert data["owner_id"] is None
        assert data["metadata"] == {"source": "nfc_reader"}

    def test_create_identifier_with_metadata(self, client):
        """Test creating identifier with custom metadata."""
        response = client.post(
            "/api/identifiers",
            json={
                "value": "metadata-test",
                "type": "UID",
                "metadata": {
                    "vendor": "acme",
                    "firmware": "1.2.3",
                    "tags": ["test", "demo"],
                },
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        metadata = response.json()["data"]["metadata"]
        assert metadata["vendor"] == "acme"
        assert metadata["tags"] == ["test", "demo"]

    def test_update_identifier_metadata(self, client, sample_identifier_data):
        """Test updating identifier metadata."""
        create_response = client.post("/api/identifiers", json=sample_identifier_data)
        identifier_id = create_response.json()["data"]["id"]

        response = client.put(
            f"/api/identifiers/{identifier_id}",
            json={"metadata": {"updated": True, "version": 2}},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["metadata"] == {"updated": True, "version": 2}

    def test_create_identifier_pan(self, client):
        """Test creating a PAN identifier."""
        response = client.post(
            "/api/identifiers", json={"value": "1234567890123456", "type": "PAN"}
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["data"]["type"] == "PAN"

    def test_create_identifier_with_owner(self, client, sample_user_data):
        """Test creating identifier with owner."""
        user_response = client.post("/api/users", json=sample_user_data)
        user_id = user_response.json()["data"]["id"]

        response = client.post(
            "/api/identifiers",
            json={"value": "test-value", "type": "UID", "owner_id": user_id},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["data"]["owner_id"] == user_id

    def test_create_identifier_duplicate(self, client, sample_identifier_data):
        """Test creating duplicate identifier fails."""
        client.post("/api/identifiers", json=sample_identifier_data)
        response = client.post("/api/identifiers", json=sample_identifier_data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_identifier(self, client, sample_identifier_data):
        """Test getting an identifier by ID."""
        create_response = client.post("/api/identifiers", json=sample_identifier_data)
        identifier_id = create_response.json()["data"]["id"]

        response = client.get(f"/api/identifiers/{identifier_id}")
        assert response.status_code == status.HTTP_200_OK

    def test_update_identifier(self, client, sample_identifier_data):
        """Test updating an identifier."""
        create_response = client.post("/api/identifiers", json=sample_identifier_data)
        identifier_id = create_response.json()["data"]["id"]

        response = client.put(
            f"/api/identifiers/{identifier_id}",
            json={"value": "new-value", "type": "PAN"},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]
        assert data["value"] == "new-value"
        assert data["type"] == "PAN"

    def test_delete_identifier(self, client, sample_identifier_data):
        """Test deleting an identifier."""
        create_response = client.post("/api/identifiers", json=sample_identifier_data)
        identifier_id = create_response.json()["data"]["id"]

        response = client.delete(f"/api/identifiers/{identifier_id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT


class TestDoorsAPI:
    """Tests for Doors API endpoints."""

    def test_list_doors_empty(self, client):
        """Test listing doors when none exist."""
        response = client.get("/api/doors")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"] == []

    def test_create_door(self, client, sample_door_data):
        """Test creating a door."""
        response = client.post("/api/doors", json=sample_door_data)
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()["data"]
        assert data["name"] == "Front Door"
        assert data["gpio_settings"]["pin"] == 17
        assert data["gpio_settings"]["pull_up"] is True

    def test_create_door_minimal_gpio(self, client):
        """Test creating door with minimal GPIO settings."""
        response = client.post(
            "/api/doors", json={"name": "Simple Door", "gpio_settings": {"pin": 22}}
        )
        assert response.status_code == status.HTTP_201_CREATED
        gpio = response.json()["data"]["gpio_settings"]
        assert gpio["pin"] == 22
        assert gpio["default_state"] is False  # Default
        assert gpio["inverted"] is False  # Default
        assert gpio["pull_up"] is False  # Default

    def test_create_door_duplicate_name(self, client, sample_door_data):
        """Test creating door with duplicate name fails."""
        client.post("/api/doors", json=sample_door_data)

        duplicate = sample_door_data.copy()
        duplicate["gpio_settings"] = {"pin": 18}
        response = client.post("/api/doors", json=duplicate)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_door_duplicate_pin(self, client, sample_door_data):
        """Test creating door with duplicate GPIO pin fails."""
        client.post("/api/doors", json=sample_door_data)

        duplicate = {"name": "Other Door", "gpio_settings": {"pin": 17}}  # Same pin
        response = client.post("/api/doors", json=duplicate)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_door(self, client, sample_door_data):
        """Test getting a door by ID."""
        create_response = client.post("/api/doors", json=sample_door_data)
        door_id = create_response.json()["data"]["id"]

        response = client.get(f"/api/doors/{door_id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["name"] == "Front Door"

    def test_update_door(self, client, sample_door_data):
        """Test updating a door."""
        create_response = client.post("/api/doors", json=sample_door_data)
        door_id = create_response.json()["data"]["id"]

        response = client.put(
            f"/api/doors/{door_id}",
            json={"name": "Back Door", "gpio_settings": {"pin": 27, "inverted": True}},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]
        assert data["name"] == "Back Door"
        assert data["gpio_settings"]["pin"] == 27
        assert data["gpio_settings"]["inverted"] is True

    def test_delete_door(self, client, sample_door_data):
        """Test deleting a door."""
        create_response = client.post("/api/doors", json=sample_door_data)
        door_id = create_response.json()["data"]["id"]

        response = client.delete(f"/api/doors/{door_id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT


class TestUserIdentifiersAPI:
    """Tests for User Identifiers management API."""

    def test_get_user_identifiers_empty(self, client, sample_user_data):
        """Test getting user identifiers when none assigned."""
        user_response = client.post("/api/users", json=sample_user_data)
        user_id = user_response.json()["data"]["id"]

        response = client.get(f"/api/users/{user_id}/identifiers")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"] == []

    def test_assign_identifier_to_user(
        self, client, sample_user_data, sample_identifier_data
    ):
        """Test assigning an identifier to a user."""
        user_response = client.post("/api/users", json=sample_user_data)
        user_id = user_response.json()["data"]["id"]

        identifier_response = client.post(
            "/api/identifiers", json=sample_identifier_data
        )
        identifier_id = identifier_response.json()["data"]["id"]

        response = client.post(
            f"/api/users/{user_id}/identifiers", json={"identifier_id": identifier_id}
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert identifier_id in response.json()["data"]["identifiers"]

    def test_get_user_identifiers_after_assign(
        self, client, sample_user_data, sample_identifier_data
    ):
        """Test getting user identifiers after assignment."""
        user_response = client.post("/api/users", json=sample_user_data)
        user_id = user_response.json()["data"]["id"]

        identifier_response = client.post(
            "/api/identifiers", json=sample_identifier_data
        )
        identifier_id = identifier_response.json()["data"]["id"]

        client.post(
            f"/api/users/{user_id}/identifiers", json={"identifier_id": identifier_id}
        )

        response = client.get(f"/api/users/{user_id}/identifiers")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 1
        assert response.json()["data"][0]["id"] == identifier_id

    def test_unassign_identifier_from_user(
        self, client, sample_user_data, sample_identifier_data
    ):
        """Test unassigning an identifier from a user."""
        user_response = client.post("/api/users", json=sample_user_data)
        user_id = user_response.json()["data"]["id"]

        identifier_response = client.post(
            "/api/identifiers", json=sample_identifier_data
        )
        identifier_id = identifier_response.json()["data"]["id"]

        # Assign
        client.post(
            f"/api/users/{user_id}/identifiers", json={"identifier_id": identifier_id}
        )

        # Unassign
        response = client.delete(f"/api/users/{user_id}/identifiers/{identifier_id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify unassigned
        get_response = client.get(f"/api/users/{user_id}/identifiers")
        assert get_response.json()["total"] == 0

    def test_assign_multiple_identifiers(self, client, sample_user_data):
        """Test assigning multiple identifiers to a user."""
        user_response = client.post("/api/users", json=sample_user_data)
        user_id = user_response.json()["data"]["id"]

        # Create and assign multiple identifiers
        for i in range(3):
            identifier_response = client.post(
                "/api/identifiers", json={"value": f"identifier-{i}", "type": "UID"}
            )
            identifier_id = identifier_response.json()["data"]["id"]
            client.post(
                f"/api/users/{user_id}/identifiers",
                json={"identifier_id": identifier_id},
            )

        response = client.get(f"/api/users/{user_id}/identifiers")
        assert response.json()["total"] == 3


class TestValidation:
    """Tests for input validation."""

    def test_create_user_empty_username(self, client):
        """Test creating user with empty username fails."""
        response = client.post("/api/users", json={"username": ""})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_user_invalid_status(self, client):
        """Test creating user with invalid status fails."""
        response = client.post(
            "/api/users", json={"username": "test", "status": "InvalidStatus"}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_identifier_invalid_type(self, client):
        """Test creating identifier with invalid type fails."""
        response = client.post(
            "/api/identifiers", json={"value": "test", "type": "INVALID"}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_door_negative_pin(self, client):
        """Test creating door with negative GPIO pin fails."""
        response = client.post(
            "/api/doors", json={"name": "Test Door", "gpio_settings": {"pin": -1}}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_door_missing_gpio(self, client):
        """Test creating door without GPIO settings fails."""
        response = client.post("/api/doors", json={"name": "Test Door"})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
