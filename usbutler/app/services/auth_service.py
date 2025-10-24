"""Authentication service with support for multiple identifiers per user."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple


class Identifier:
    """Represents a stable identifier associated with a user."""

    def __init__(
        self,
        value: str,
        identifier_type: str = "PAN",
        primary: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.value = value
        self.type = identifier_type or "PAN"
        self.primary = primary
        self.metadata: Dict[str, Any] = metadata.copy() if metadata else {}

    def mask(self) -> str:
        if len(self.value) <= 4:
            return self.value
        return f"****{self.value[-4:]}"

    def to_dict(self) -> Dict[str, object]:
        return {
            "value": self.value,
            "type": self.type,
            "primary": self.primary,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Identifier":
        return cls(
            value=str(data.get("value", "")),
            identifier_type=str(data.get("type", "PAN")),
            primary=bool(data.get("primary", False)),
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else None,
        )


class User:
    """User data model supporting multiple identifiers."""

    def __init__(
        self,
        user_id: str,
        name: str,
        access_level: str = "user",
        active: bool = True,
        identifiers: Optional[List[Identifier]] = None,
    ):
        self.user_id = user_id
        self.name = name
        self.access_level = access_level
        self.active = active
        self.identifiers: List[Identifier] = identifiers[:] if identifiers else []
        if self.identifiers and not any(identifier.primary for identifier in self.identifiers):
            # Ensure we always have a primary identifier if any identifiers exist
            self.identifiers[0].primary = True

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "access_level": self.access_level,
            "active": self.active,
            "identifiers": [identifier.to_dict() for identifier in self.identifiers],
        }

    @classmethod
    def from_dict(cls, user_id: str, data: Dict[str, object]) -> "User":
        identifiers_data = data.get("identifiers", [])
        identifiers = [Identifier.from_dict(item) for item in identifiers_data]
        user = cls(
            user_id=user_id,
            name=str(data.get("name", "Unknown")),
            access_level=str(data.get("access_level", "user")),
            active=bool(data.get("active", True)),
            identifiers=identifiers,
        )
        return user

    @classmethod
    def from_legacy_record(
        cls,
        identifier_value: str,
        payload: Dict[str, object],
        identifier_type: str = "PAN",
    ) -> "User":
        user = cls(
            user_id=str(uuid.uuid4()),
            name=str(payload.get("name", "Unknown")),
            access_level=str(payload.get("access_level", "user")),
            active=bool(payload.get("active", True)),
            identifiers=[Identifier(identifier_value, identifier_type, primary=True)],
        )
        return user

    def primary_identifier(self) -> Optional[Identifier]:
        for identifier in self.identifiers:
            if identifier.primary:
                return identifier
        return self.identifiers[0] if self.identifiers else None

    def add_identifier(self, identifier: Identifier, make_primary: bool = False) -> None:
        if any(item.value == identifier.value for item in self.identifiers):
            return
        if make_primary or not self.identifiers:
            for existing in self.identifiers:
                existing.primary = False
            identifier.primary = True
        self.identifiers.append(identifier)
        if identifier.primary:
            for other in self.identifiers:
                if other is not identifier:
                    other.primary = False

    def remove_identifier(self, value: str) -> bool:
        removed = False
        remaining: List[Identifier] = []
        for identifier in self.identifiers:
            if identifier.value == value:
                removed = True
                continue
            remaining.append(identifier)
        self.identifiers = remaining
        if self.identifiers and not any(item.primary for item in self.identifiers):
            self.identifiers[0].primary = True
        return removed

    def set_primary_identifier(self, value: str) -> bool:
        found = False
        for identifier in self.identifiers:
            if identifier.value == value:
                identifier.primary = True
                found = True
            else:
                identifier.primary = False
        return found


class AuthenticationService:
    """Service for user authentication and management"""

    def __init__(self, db_file: str = "users.json"):
        self.db_file = db_file
        self.users, self.identifier_index = self._load_users()
        self._db_mtime = None  # type: Optional[float]
        self._update_db_mtime()

    def authenticate_user(self, pan: str) -> Optional[User]:
        """
        Authenticate a user by their PAN
        Returns User object if authentication successful, None otherwise
        """
        user_id = self.identifier_index.get(pan)
        if not user_id:
            return None
        user = self.users.get(user_id)
        if user and user.active:
            return user
        return None

    def add_user(self, pan: str, name: str, access_level: str = "user") -> bool:
        """
        Add a new user to the system
        Returns True if successful, False if user already exists
        """
        if pan in self.identifier_index:
            return False

        self.create_user(
            identifier_value=pan,
            name=name,
            access_level=access_level,
            identifier_type="PAN",
        )
        return True

    def create_user(
        self,
        identifier_value: str,
        name: str,
        access_level: str = "user",
        identifier_type: str = "PAN",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> User:
        user_id = str(uuid.uuid4())
        user = User(user_id=user_id, name=name, access_level=access_level, active=True)
        user.add_identifier(
            Identifier(
                identifier_value,
                identifier_type,
                primary=True,
                metadata=metadata,
            )
        )
        self.users[user_id] = user
        self.identifier_index[identifier_value] = user_id
        self._save_users()
        return user

    def add_identifier_to_user(
        self,
        user_id: str,
        identifier_value: str,
        identifier_type: str = "UID",
        make_primary: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if identifier_value in self.identifier_index:
            return False
        user = self.users.get(user_id)
        if not user:
            return False
        user.add_identifier(
            Identifier(
                identifier_value,
                identifier_type,
                primary=make_primary,
                metadata=metadata,
            )
        )
        self.identifier_index[identifier_value] = user_id
        self._save_users()
        return True

    def remove_user(self, pan: str) -> bool:
        """
        Remove a specific identifier from the system. If it was the user's last
        identifier, the user record will be removed as well.
        Returns True if successful, False if user doesn't exist
        """
        user_id = self.identifier_index.get(pan)
        if not user_id:
            return False

        user = self.users.get(user_id)
        if not user:
            return False

        removed = user.remove_identifier(pan)
        if not removed:
            return False

        del self.identifier_index[pan]
        if not user.identifiers:
            del self.users[user_id]
        self._save_users()
        return True

    def remove_identifier_from_user(self, user_id: str, identifier_value: str) -> bool:
        user = self.users.get(user_id)
        if not user:
            return False
        removed = user.remove_identifier(identifier_value)
        if not removed:
            return False
        self.identifier_index.pop(identifier_value, None)
        if not user.identifiers:
            del self.users[user_id]
        self._save_users()
        return True

    def delete_user(self, user_id: str) -> bool:
        user = self.users.get(user_id)
        if not user:
            return False
        for identifier in user.identifiers:
            self.identifier_index.pop(identifier.value, None)
        del self.users[user_id]
        self._save_users()
        return True

    def deactivate_user(self, pan: str) -> bool:
        """
        Deactivate a user (keep in database but deny access)
        Returns True if successful, False if user doesn't exist
        """
        user = self.authenticate_user(pan)
        if not user:
            return False
        user.active = False
        self._save_users()
        return True

    def set_user_active(self, user_id: str, active: bool) -> bool:
        user = self.users.get(user_id)
        if not user:
            return False
        user.active = active
        self._save_users()
        return True

    def activate_user(self, pan: str) -> bool:
        """
        Activate a user
        Returns True if successful, False if user doesn't exist
        """
        user = self.authenticate_user(pan)
        if not user:
            return False
        user.active = True
        self._save_users()
        return True

    def list_users(self) -> Dict[str, User]:
        """List all users in the system"""
        return self.users.copy()

    def refresh_from_disk(self, force: bool = False) -> bool:
        """Reload the user database if the backing file has changed.

        Returns True when a reload occurred.
        """

        current_mtime = self._get_db_mtime()
        if not force and current_mtime == self._db_mtime:
            return False

        self.users, self.identifier_index = self._load_users()
        self._update_db_mtime()
        return True

    def get_user_count(self) -> int:
        """Get total number of users"""
        return len(self.users)

    def get_active_user_count(self) -> int:
        """Get number of active users"""
        return sum(1 for user in self.users.values() if user.active)

    def get_user(self, user_id: str) -> Optional[User]:
        return self.users.get(user_id)

    def identifier_exists(self, identifier_value: str) -> bool:
        return identifier_value in self.identifier_index

    def set_primary_identifier(self, user_id: str, identifier_value: str) -> bool:
        user = self.users.get(user_id)
        if not user:
            return False
        success = user.set_primary_identifier(identifier_value)
        if success:
            self._save_users()
        return success

    def find_user_by_identifier(self, identifier_value: str) -> Optional[User]:
        user_id = self.identifier_index.get(identifier_value)
        if not user_id:
            return None
        return self.users.get(user_id)

    def _load_users(self) -> Dict[str, User]:
        """Load users from JSON file"""
        try:
            with open(self.db_file, "r") as f:
                raw_data = json.load(f)
        except FileNotFoundError:
            default_records = {
                "4111111111111111": {"name": "John Doe", "access_level": "admin", "active": True},
                "5555555555554444": {"name": "Jane Smith", "access_level": "user", "active": True},
            }
            users, index = self._convert_legacy_records(default_records)
            self._save_users_dict(users)
            return users, index

        if not raw_data:
            return {}, {}

        if isinstance(raw_data, dict) and "users" in raw_data:
            users: Dict[str, User] = {}
            index: Dict[str, str] = {}
            for user_id, payload in raw_data.get("users", {}).items():
                user = User.from_dict(user_id, payload)
                if not user.identifiers:
                    continue
                users[user_id] = user
                for identifier in user.identifiers:
                    index[identifier.value] = user_id
            return users, index

        if isinstance(raw_data, dict):
            users, index = self._convert_legacy_records(raw_data)
            self._save_users_dict(users)
            return users, index

        # Fallback to empty structure if the file contents are not recognised
        return {}, {}

    def _convert_legacy_records(
        self, legacy: Dict[str, Dict[str, object]]
    ) -> Tuple[Dict[str, User], Dict[str, str]]:
        users: Dict[str, User] = {}
        index: Dict[str, str] = {}
        for identifier_value, payload in legacy.items():
            user = User.from_legacy_record(identifier_value, payload)
            users[user.user_id] = user
            index[identifier_value] = user.user_id
        return users, index

    def _save_users(self):
        """Save current users to JSON file"""
        self._save_users_dict(self.users)

    def _save_users_dict(self, users: Dict[str, User]):
        """Persist users in the modern storage format."""
        payload = {
            "version": 2,
            "users": {user_id: user.to_dict() for user_id, user in users.items()},
        }
        with open(self.db_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        self._update_db_mtime()

    def _get_db_mtime(self) -> Optional[float]:
        try:
            return os.path.getmtime(self.db_file)
        except OSError:
            return None

    def _update_db_mtime(self) -> None:
        self._db_mtime = self._get_db_mtime()
