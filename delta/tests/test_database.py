import pytest

from database import JsonDatabase


class TestJsonDatabase:
    """Tests for the JSON database layer."""

    def test_database_initialization(self, temp_db_path):
        """Test database creates file on initialization."""
        db = JsonDatabase(temp_db_path)
        assert db.db_path.exists()

    def test_generate_id(self, db):
        """Test ID generation returns unique UUIDs."""
        id1 = db.generate_id()
        id2 = db.generate_id()
        assert id1 != id2
        assert len(id1) == 36  # UUID format

    def test_create_and_get(self, db):
        """Test creating and retrieving an item."""
        item = {"name": "test", "value": 123}
        db.create("test_collection", "item1", item)

        result = db.get_by_id("test_collection", "item1")
        assert result == item

    def test_get_nonexistent(self, db):
        """Test getting a nonexistent item returns None."""
        result = db.get_by_id("test_collection", "nonexistent")
        assert result is None

    def test_get_all(self, db):
        """Test getting all items from a collection."""
        db.create("test_collection", "item1", {"name": "first"})
        db.create("test_collection", "item2", {"name": "second"})

        all_items = db.get_all("test_collection")
        assert len(all_items) == 2
        assert "item1" in all_items
        assert "item2" in all_items

    def test_get_all_empty_collection(self, db):
        """Test getting all items from empty collection."""
        result = db.get_all("empty_collection")
        assert result == {}

    def test_update(self, db):
        """Test updating an existing item."""
        db.create("test_collection", "item1", {"name": "original"})

        updated = db.update("test_collection", "item1", {"name": "updated"})
        assert updated["name"] == "updated"

        result = db.get_by_id("test_collection", "item1")
        assert result["name"] == "updated"

    def test_update_nonexistent(self, db):
        """Test updating a nonexistent item returns None."""
        result = db.update("test_collection", "nonexistent", {"name": "test"})
        assert result is None

    def test_delete(self, db):
        """Test deleting an item."""
        db.create("test_collection", "item1", {"name": "test"})

        result = db.delete("test_collection", "item1")
        assert result is True
        assert db.get_by_id("test_collection", "item1") is None

    def test_delete_nonexistent(self, db):
        """Test deleting a nonexistent item returns False."""
        result = db.delete("test_collection", "nonexistent")
        assert result is False

    def test_find_by_field(self, db):
        """Test finding items by field value."""
        db.create("test_collection", "item1", {"name": "alice", "role": "admin"})
        db.create("test_collection", "item2", {"name": "bob", "role": "user"})
        db.create("test_collection", "item3", {"name": "charlie", "role": "admin"})

        admins = db.find_by_field("test_collection", "role", "admin")
        assert len(admins) == 2

    def test_find_by_fields(self, db):
        """Test finding items by multiple fields."""
        db.create(
            "test_collection",
            "item1",
            {"name": "alice", "role": "admin", "active": True},
        )
        db.create(
            "test_collection",
            "item2",
            {"name": "bob", "role": "admin", "active": False},
        )
        db.create(
            "test_collection",
            "item3",
            {"name": "charlie", "role": "user", "active": True},
        )

        result = db.find_by_fields("test_collection", {"role": "admin", "active": True})
        assert len(result) == 1
        assert result[0]["name"] == "alice"
