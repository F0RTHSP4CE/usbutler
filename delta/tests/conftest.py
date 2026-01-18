import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Add delta directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import app
from database import JsonDatabase, get_database


@pytest.fixture
def temp_db_path():
    """Create a temporary database file path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "test_db.json")


@pytest.fixture
def db(temp_db_path):
    """Create a fresh database instance for each test."""
    return JsonDatabase(temp_db_path)


@pytest.fixture
def client(db):
    """Create a test client with a fresh database."""

    def override_get_database():
        return db

    app.dependency_overrides[get_database] = override_get_database

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_user_data():
    """Sample user creation data."""
    return {"username": "testuser", "status": "Active"}


@pytest.fixture
def sample_identifier_data():
    """Sample identifier creation data."""
    return {
        "value": "04:AA:BB:CC:DD:EE:FF",
        "type": "UID",
        "metadata": {"source": "nfc_reader"},
    }


@pytest.fixture
def sample_door_data():
    """Sample door creation data."""
    return {
        "name": "Front Door",
        "gpio_settings": {
            "pin": 17,
            "default_state": False,
            "inverted": False,
            "pull_up": True,
        },
    }
