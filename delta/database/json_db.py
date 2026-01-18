import json
import os
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4


class JsonDatabase:
    """File-based JSON database with thread-safe operations."""

    def __init__(self, db_path: str = "data/db.json"):
        self.db_path = Path(db_path)
        self._lock = Lock()
        self._ensure_db_exists()

    def _ensure_db_exists(self) -> None:
        """Ensure database file and directory exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self._write_data({"users": {}, "identifiers": {}, "doors": {}})

    def _read_data(self) -> dict[str, Any]:
        """Read all data from the database file."""
        with open(self.db_path, "r") as f:
            return json.load(f)

    def _write_data(self, data: dict[str, Any]) -> None:
        """Write data to the database file."""
        with open(self.db_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def generate_id(self) -> str:
        """Generate a unique ID."""
        return str(uuid4())

    # Generic CRUD operations
    def get_all(self, collection: str) -> dict[str, Any]:
        """Get all items from a collection."""
        with self._lock:
            data = self._read_data()
            return data.get(collection, {})

    def get_by_id(self, collection: str, item_id: str) -> dict[str, Any] | None:
        """Get a single item by ID."""
        with self._lock:
            data = self._read_data()
            return data.get(collection, {}).get(item_id)

    def create(
        self, collection: str, item_id: str, item: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a new item in a collection."""
        with self._lock:
            data = self._read_data()
            if collection not in data:
                data[collection] = {}
            data[collection][item_id] = item
            self._write_data(data)
            return item

    def update(
        self, collection: str, item_id: str, item: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update an existing item."""
        with self._lock:
            data = self._read_data()
            if collection not in data or item_id not in data[collection]:
                return None
            data[collection][item_id] = item
            self._write_data(data)
            return item

    def delete(self, collection: str, item_id: str) -> bool:
        """Delete an item from a collection."""
        with self._lock:
            data = self._read_data()
            if collection not in data or item_id not in data[collection]:
                return False
            del data[collection][item_id]
            self._write_data(data)
            return True

    def find_by_field(
        self, collection: str, field: str, value: Any
    ) -> list[dict[str, Any]]:
        """Find items by a specific field value."""
        with self._lock:
            data = self._read_data()
            items = data.get(collection, {})
            return [item for item in items.values() if item.get(field) == value]

    def find_by_fields(
        self, collection: str, filters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Find items matching multiple field values."""
        with self._lock:
            data = self._read_data()
            items = data.get(collection, {})
            results = []
            for item in items.values():
                if all(item.get(k) == v for k, v in filters.items()):
                    results.append(item)
            return results


# Singleton instance
_database: JsonDatabase | None = None


def get_database() -> JsonDatabase:
    """Dependency injection for database access."""
    global _database
    if _database is None:
        db_path = os.environ.get("DB_PATH", "data/db.json")
        _database = JsonDatabase(db_path)
    return _database
