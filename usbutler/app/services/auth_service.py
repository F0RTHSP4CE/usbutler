"""Authentication service with support for multiple identifiers per user."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any


ALLOWED_ACCESS_LEVELS = {"user", "admin"}


class AuthServiceError(Exception):
    """Base error for authentication service operations."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.message = message
        super().__init__(message or code)


class UserNotFoundError(AuthServiceError):
    def __init__(self, message: str | None = None):
        super().__init__("not_found", message)


class IdentifierNotFoundError(AuthServiceError):
    def __init__(self, message: str | None = None):
        super().__init__("not_found", message)


class IdentifierExistsError(AuthServiceError):
    def __init__(self, existing_user: "User | None" = None, message: str | None = None):
        super().__init__("user_exists", message)
        self.existing_user = existing_user


class InvalidAccessLevelError(AuthServiceError):
    def __init__(self, message: str | None = None):
        super().__init__("invalid_access_level", message)


class MissingNameError(AuthServiceError):
    def __init__(self, message: str | None = None):
        super().__init__("missing_name", message)


@dataclass(slots=True)
class Identifier:
    """Represents a stable identifier associated with a user."""

    value: str
    type: str = "PAN"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "type": self.type,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Identifier":
        metadata = data.get("metadata")
        return cls(
            value=str(data.get("value", "")),
            type=str(data.get("type", "PAN") or "PAN"),
            metadata=metadata if isinstance(metadata, dict) else {},
        )


@dataclass(slots=True)
class User:
    """User data model supporting multiple identifiers."""

    user_id: str
    name: str
    access_level: str = "user"
    active: bool = True
    identifiers: list[Identifier] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "access_level": self.access_level,
            "active": self.active,
            "identifiers": [identifier.to_dict() for identifier in self.identifiers],
        }

    @classmethod
    def from_dict(cls, user_id: str, data: dict[str, Any]) -> "User":
        identifiers_data = data.get("identifiers", [])
        if not isinstance(identifiers_data, list):
            identifiers_data = []
        identifiers = [Identifier.from_dict(item) for item in identifiers_data]
        return cls(
            user_id=user_id,
            name=str(data.get("name", "Unknown")),
            access_level=str(data.get("access_level", "user")),
            active=bool(data.get("active", True)),
            identifiers=identifiers,
        )

    def add_identifier(self, identifier: Identifier) -> bool:
        if any(item.value == identifier.value for item in self.identifiers):
            return False
        self.identifiers.append(identifier)
        return True

    def remove_identifier(self, value: str) -> bool:
        original_len = len(self.identifiers)
        self.identifiers = [item for item in self.identifiers if item.value != value]
        return len(self.identifiers) != original_len


class AuthService:
    """Service for user authentication and management"""

    def __init__(self, db_file: str = "users.json"):
        self.db_file = db_file
        self.users, self.identifier_index = self._load_users()

    def authenticate_user(self, identifier_value: str) -> User | None:
        """Authenticate a user by identifier value."""
        user_id = self.identifier_index.get(identifier_value)
        if not user_id:
            return None
        user = self.users.get(user_id)
        if user and user.active:
            return user
        return None

    def create_user_or_raise(
        self,
        identifier_value: str,
        name: str,
        access_level: str = "user",
        identifier_type: str = "PAN",
        metadata: dict[str, Any] | None = None,
    ) -> User:
        if identifier_value in self.identifier_index:
            existing_user = self.users.get(
                self.identifier_index.get(identifier_value, "")
            )
            raise IdentifierExistsError(existing_user)
        if not name:
            raise MissingNameError("missing_name")
        if access_level not in ALLOWED_ACCESS_LEVELS:
            raise InvalidAccessLevelError("invalid_access_level")
        user_id = str(uuid.uuid4())
        user = User(user_id=user_id, name=name, access_level=access_level, active=True)
        user.add_identifier(
            Identifier(
                identifier_value,
                identifier_type or "PAN",
                metadata=metadata or {},
            )
        )
        self.identifier_index[identifier_value] = user_id
        self.users[user_id] = user
        self._save_users()
        return user

    def add_identifier_to_user_or_raise(
        self,
        user_id: str,
        identifier_value: str,
        identifier_type: str = "UID",
        metadata: dict[str, Any] | None = None,
    ) -> User:
        if identifier_value in self.identifier_index:
            existing_user = self.users.get(
                self.identifier_index.get(identifier_value, "")
            )
            raise IdentifierExistsError(existing_user)
        user = self.users.get(user_id)
        if not user:
            raise UserNotFoundError("not_found")
        user.add_identifier(
            Identifier(
                identifier_value,
                identifier_type or "UID",
                metadata=metadata or {},
            )
        )
        self.identifier_index[identifier_value] = user_id
        self._save_users()
        return user

    def remove_identifier_from_user_or_raise(
        self, user_id: str, identifier_value: str
    ) -> tuple[User | None, bool]:
        user = self.users.get(user_id)
        if not user:
            raise UserNotFoundError("not_found")
        removed = user.remove_identifier(identifier_value)
        if not removed:
            raise IdentifierNotFoundError("not_found")
        self.identifier_index.pop(identifier_value, None)
        user_removed = False
        if not user.identifiers:
            del self.users[user_id]
            user_removed = True
        self._save_users()
        return (None if user_removed else user, user_removed)

    def delete_user_or_raise(self, user_id: str) -> None:
        user = self.users.get(user_id)
        if not user:
            raise UserNotFoundError("not_found")
        for identifier in user.identifiers:
            self.identifier_index.pop(identifier.value, None)
        del self.users[user_id]
        self._save_users()

    def set_user_active_or_raise(self, user_id: str, active: bool) -> User:
        user = self.users.get(user_id)
        if not user:
            raise UserNotFoundError("not_found")
        user.active = active
        self._save_users()
        return user

    def list_users(self) -> list[User]:
        """List all users in the system."""
        return list(self.users.values())

    def find_user_by_identifier_or_raise(self, identifier_value: str) -> User:
        user = self.users.get(self.identifier_index.get(identifier_value, ""))
        if not user:
            raise UserNotFoundError("not_found")
        return user

    def _load_users(self) -> tuple[dict[str, User], dict[str, str]]:
        """Load users from JSON file."""
        try:
            with open(self.db_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}, {}

        if not raw_data:
            return {}, {}

        if isinstance(raw_data, dict) and "users" in raw_data:
            users: dict[str, User] = {}
            index: dict[str, str] = {}
            for user_id, payload in raw_data.get("users", {}).items():
                if not isinstance(payload, dict):
                    continue
                user = User.from_dict(user_id, payload)
                if not user.identifiers:
                    continue
                users[user_id] = user
                for identifier in user.identifiers:
                    index[identifier.value] = user_id
            return users, index

        # Fallback to empty structure if the file contents are not recognised
        return {}, {}

    def _save_users(self) -> None:
        payload = {
            "users": {user_id: user.to_dict() for user_id, user in self.users.items()},
        }
        with open(self.db_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
