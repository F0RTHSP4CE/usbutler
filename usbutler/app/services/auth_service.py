"""Authentication service for card-based access control."""

from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models.identifier import Identifier
from app.models.user import User, UserStatus
from app.services.identifier_service import IdentifierService
from app.services.user_service import UserService


class AuthService:
    """Service for authenticating users by identifier."""

    def __init__(self, db: Session):
        self.db = db
        self.user_service = UserService(db)
        self.identifier_service = IdentifierService(db)

    def authenticate_by_identifier(
        self, identifier_value: str
    ) -> Tuple[bool, Optional[User], Optional[Identifier], str]:
        """
        Authenticate a user by their identifier.

        Returns:
            Tuple of (success, user, identifier, message)
        """
        # Find the identifier
        identifier = self.identifier_service.get_by_value(identifier_value)

        if not identifier:
            return False, None, None, "Unknown identifier"

        # Check if identifier is assigned to a user
        if not identifier.user_id:
            return False, None, identifier, "Identifier not assigned to any user"

        # Get the user
        user = self.user_service.get_by_id(identifier.user_id)

        if not user:
            return False, None, identifier, "User not found"

        # Check if user is active
        if user.status != UserStatus.ACTIVE:
            return False, user, identifier, f"User is {user.status.value}"

        return True, user, identifier, "Authentication successful"

    def get_user_by_identifier(self, identifier_value: str) -> Optional[User]:
        """Get user by identifier value (convenience method)."""
        success, user, _, _ = self.authenticate_by_identifier(identifier_value)
        return user if success else None
