"""Authentication service for card-based access control."""

from typing import Optional, Tuple

from app.models.identifier import Identifier, IdentifierType
from app.models.user import User, UserStatus
from app.services.card_reader import CardScanResult
from app.services.mifare_rotation_service import MifareRotationService

AuthResult = Tuple[bool, Optional[User], Optional[Identifier], str]


class AuthService:
    """Authenticates ordinary identifiers and structured physical card scans."""

    def __init__(self, user_service, identifier_service):
        self.users = user_service
        self.identifiers = identifier_service

    def authenticate(self, identifier_value: str) -> AuthResult:
        """Authenticate a regular PAN/UID value."""
        identifier = self.identifiers.get_by_value(identifier_value)
        if not identifier:
            return False, None, None, "Unknown identifier"
        return self._authenticate_identifier(identifier)

    def authenticate_card(self, scan: CardScanResult) -> AuthResult:
        """Prefer MIFARE block data and allow UID only before enrollment."""
        if not scan.mifare_classic:
            value = scan.identifier()
            return (
                self.authenticate(value)
                if value
                else (False, None, None, "Card has no identifier")
            )

        rotation = MifareRotationService(self.identifiers.db)
        if scan.mifare_uuid:
            uuid_record = rotation.get_uuid_record(scan.mifare_uuid)
            if uuid_record:
                return self._authenticate_identifier(uuid_record.credential.identifier)

        identifier = self.identifiers.get_by_value(scan.uid) if scan.uid else None
        if not identifier or identifier.type != IdentifierType.UID:
            return False, None, None, "Unknown MIFARE credential"
        if rotation.has_confirmed_uuid(identifier.id):
            return (
                False,
                None,
                identifier,
                "Enrolled MIFARE credential requires a recognized data UUID",
            )
        return self._authenticate_identifier(identifier)

    def _authenticate_identifier(self, identifier: Identifier) -> AuthResult:
        if not identifier.user_id:
            return False, None, identifier, "Identifier not assigned"

        user = self.users.get_by_id(identifier.user_id)
        if not user:
            return False, None, identifier, "User not found"

        if user.status != UserStatus.ACTIVE:
            return False, user, identifier, f"User is {user.status.value}"

        return True, user, identifier, "OK"
