"""Authentication service for card-based access control."""

from typing import Optional, Tuple

from app.models.identifier import Identifier
from app.models.user import User, UserStatus


class AuthService:
    """Authenticates users by identifier."""

    def __init__(self, user_service, identifier_service):
        self.users = user_service
        self.identifiers = identifier_service

    def authenticate(
        self, identifier_value: str
    ) -> Tuple[bool, Optional[User], Optional[Identifier], str]:
        """Authenticate by identifier. Returns (success, user, identifier, message)."""
        identifier = self.identifiers.get_by_value(identifier_value)
        if not identifier:
            return False, None, None, "Unknown identifier"

        if not identifier.user_id:
            return False, None, identifier, "Identifier not assigned"

        user = self.users.get_by_id(identifier.user_id)
        if not user:
            return False, None, identifier, "User not found"

        if user.status != UserStatus.ACTIVE:
            return False, user, identifier, f"User is {user.status.value}"

        return True, user, identifier, "OK"
