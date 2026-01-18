"""Authentication service with support for multiple identifiers per user."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from pydantic import BaseModel, Field


ALLOWED_ACCESS_LEVELS = {"user", "admin"}


class AuthServiceError(Exception):
    """Base error for authentication service operations."""

    code: str = "error"
    default_message: str = "An error occurred"

    def __init__(self, message: str | None = None, **kwargs):
        self.code = self.__class__.code
        self.message = message or self.default_message
        for key, value in kwargs.items():
            setattr(self, key, value)
        super().__init__(self.message)


class UserNotFoundError(AuthServiceError):
    code = "not_found"
    default_message = "User not found"


class IdentifierNotFoundError(AuthServiceError):
    code = "not_found"
    default_message = "Identifier not found"


class IdentifierExistsError(AuthServiceError):
    code = "user_exists"
    default_message = "Identifier already exists"
    existing_user: "User | None" = None


class InvalidAccessLevelError(AuthServiceError):
    code = "invalid_access_level"
    default_message = "Invalid access level"


class MissingNameError(AuthServiceError):
    code = "missing_name"
    default_message = "Name is required"


class Identifier(BaseModel):
    """Represents a stable identifier associated with a user."""

    value: str
    type: str = "PAN"
    metadata: dict[str, Any] = Field(default_factory=dict)


class User(BaseModel):
    """User data model supporting multiple identifiers."""

    user_id: str
    name: str
    access_level: str = "user"
    active: bool = True
    identifiers: list[Identifier] = Field(default_factory=list)

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

    def get_user_or_raise(self, user_id: str) -> User:
        """Get a user by ID or raise UserNotFoundError."""
        user = self.users.get(user_id)
        if not user:
            raise UserNotFoundError("User not found")
        return user

    def update_user_or_raise(
        self,
        user_id: str,
        name: str | None = None,
        access_level: str | None = None,
        active: bool | None = None,
    ) -> User:
        """Update user details. Only provided fields are updated."""
        user = self.users.get(user_id)
        if not user:
            raise UserNotFoundError("User not found")

        if name is not None:
            if not name.strip():
                raise MissingNameError("Name cannot be empty")
            user.name = name.strip()

        if access_level is not None:
            if access_level not in ALLOWED_ACCESS_LEVELS:
                raise InvalidAccessLevelError(f"Invalid access level: {access_level}")
            user.access_level = access_level

        if active is not None:
            user.active = active

        self._save_users()
        return user

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
                user = User(user_id=user_id, **payload)
                if not user.identifiers:
                    continue
                users[user_id] = user
                for identifier in user.identifiers:
                    index[identifier.value] = user_id
            return users, index

        return {}, {}

    def _save_users(self) -> None:
        payload = {
            "users": {
                user_id: user.model_dump(exclude={"user_id"})
                for user_id, user in self.users.items()
            },
        }
        with open(self.db_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
