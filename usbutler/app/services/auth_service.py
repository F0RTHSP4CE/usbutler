"""Authentication service for card-based access control."""

from dataclasses import dataclass
from enum import Enum
from typing import Iterator, Optional, Tuple, Union, overload

from app.models.identifier import Identifier, IdentifierType
from app.models.user import User, UserStatus
from app.services.card_reader import CardScanResult
from app.services.mifare_rotation_service import MifareRotationService

AuthResult = Tuple[bool, Optional[User], Optional[Identifier], str]


class CardAuthAnomaly(str, Enum):
    """Security-relevant conditions observed during card authentication."""

    UNKNOWN_CARD = "Unknown card"
    DISABLED_USER = "Disabled user attempted access"
    ENROLLED_UUID_REJECTED = (
        "Enrolled card used without a recognized current or recent data UUID"
    )
    UID_UUID_MISMATCH = "UID does not correspond to the recognized data UUID"
    UNRECOGNIZED_DATA_UUID = "Unrecognized data UUID found on a legacy card"
    UID_UNREADABLE = "UID could not be read for a recognized data UUID"
    UNASSIGNED_IDENTIFIER = "Registered card is not assigned to a user"
    MISSING_USER = "Registered card refers to a missing user"


@dataclass(frozen=True)
class CardAuthResult:
    """Card decision plus anomaly context for asynchronous alerting.

    Iteration and indexing intentionally expose the original four-item result so
    existing callers do not need to migrate atomically.
    """

    success: bool
    user: Optional[User]
    identifier: Optional[Identifier]
    message: str
    anomalies: Tuple[CardAuthAnomaly, ...] = ()
    uid_identifier: Optional[Identifier] = None
    uuid_identifier: Optional[Identifier] = None

    def _legacy(self) -> AuthResult:
        return self.success, self.user, self.identifier, self.message

    def __iter__(self) -> Iterator[object]:
        return iter(self._legacy())

    def __len__(self) -> int:
        return 4

    @overload
    def __getitem__(self, index: int) -> object: ...

    @overload
    def __getitem__(self, index: slice) -> AuthResult: ...

    def __getitem__(self, index: Union[int, slice]) -> object:
        return self._legacy()[index]


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

    def authenticate_card(self, scan: CardScanResult) -> CardAuthResult:
        """Prefer MIFARE block data and report credential inconsistencies."""
        if not scan.mifare_classic:
            value = scan.identifier()
            if not value:
                return CardAuthResult(
                    False,
                    None,
                    None,
                    "Card has no identifier",
                    (CardAuthAnomaly.UNKNOWN_CARD,),
                )
            identifier = self.identifiers.get_by_value(value)
            if not identifier:
                return CardAuthResult(
                    False,
                    None,
                    None,
                    "Unknown identifier",
                    (CardAuthAnomaly.UNKNOWN_CARD,),
                )
            return self._card_result(identifier)

        rotation = MifareRotationService(self.identifiers.db)
        uid_identifier = self.identifiers.get_by_value(scan.uid) if scan.uid else None
        if uid_identifier and uid_identifier.type != IdentifierType.UID:
            uid_identifier = None

        uuid_identifier = None
        if scan.mifare_uuid:
            uuid_record = rotation.get_uuid_record(scan.mifare_uuid)
            if uuid_record:
                uuid_identifier = uuid_record.credential.identifier

        if uuid_identifier:
            anomalies = []
            if not scan.uid:
                anomalies.append(CardAuthAnomaly.UID_UNREADABLE)
            elif not self._uids_match(scan.uid, uuid_identifier.value):
                anomalies.append(CardAuthAnomaly.UID_UUID_MISMATCH)

            # UUID authentication has precedence, but a disabled UID owner is
            # still security-relevant when two registered credentials conflict.
            if (
                uid_identifier
                and uid_identifier.id != uuid_identifier.id
                and uid_identifier.user
                and uid_identifier.user.status != UserStatus.ACTIVE
            ):
                anomalies.append(CardAuthAnomaly.DISABLED_USER)

            return self._card_result(
                uuid_identifier,
                anomalies=tuple(anomalies),
                uid_identifier=uid_identifier,
                uuid_identifier=uuid_identifier,
            )

        if not uid_identifier:
            return CardAuthResult(
                False,
                None,
                None,
                "Unknown MIFARE credential",
                (CardAuthAnomaly.UNKNOWN_CARD,),
                uid_identifier=None,
                uuid_identifier=None,
            )

        if rotation.has_confirmed_uuid(uid_identifier.id):
            _, user, _, _ = self._authenticate_identifier(uid_identifier)
            anomalies = [CardAuthAnomaly.ENROLLED_UUID_REJECTED]
            self._append_user_anomaly(anomalies, uid_identifier, user)
            return CardAuthResult(
                False,
                user,
                uid_identifier,
                "Enrolled MIFARE credential requires a recognized data UUID",
                self._unique(anomalies),
                uid_identifier=uid_identifier,
                uuid_identifier=None,
            )

        legacy_anomalies = (
            (CardAuthAnomaly.UNRECOGNIZED_DATA_UUID,) if scan.mifare_uuid else ()
        )
        return self._card_result(
            uid_identifier,
            anomalies=legacy_anomalies,
            uid_identifier=uid_identifier,
            uuid_identifier=None,
        )

    def _authenticate_identifier(self, identifier: Identifier) -> AuthResult:
        if not identifier.user_id:
            return False, None, identifier, "Identifier not assigned"

        user = self.users.get_by_id(identifier.user_id)
        if not user:
            return False, None, identifier, "User not found"

        if user.status != UserStatus.ACTIVE:
            return False, user, identifier, f"User is {user.status.value}"

        return True, user, identifier, "OK"

    def _card_result(
        self,
        identifier: Identifier,
        anomalies: Tuple[CardAuthAnomaly, ...] = (),
        uid_identifier: Optional[Identifier] = None,
        uuid_identifier: Optional[Identifier] = None,
    ) -> CardAuthResult:
        success, user, authenticated_identifier, message = (
            self._authenticate_identifier(identifier)
        )
        combined = list(anomalies)
        self._append_user_anomaly(combined, identifier, user)
        return CardAuthResult(
            success,
            user,
            authenticated_identifier,
            message,
            self._unique(combined),
            uid_identifier=uid_identifier,
            uuid_identifier=uuid_identifier,
        )

    @staticmethod
    def _append_user_anomaly(
        anomalies: list[CardAuthAnomaly],
        identifier: Identifier,
        user: Optional[User],
    ) -> None:
        if not identifier.user_id:
            anomalies.append(CardAuthAnomaly.UNASSIGNED_IDENTIFIER)
        elif not user:
            anomalies.append(CardAuthAnomaly.MISSING_USER)
        elif user.status != UserStatus.ACTIVE:
            anomalies.append(CardAuthAnomaly.DISABLED_USER)

    @staticmethod
    def _unique(
        anomalies: list[CardAuthAnomaly],
    ) -> Tuple[CardAuthAnomaly, ...]:
        return tuple(dict.fromkeys(anomalies))

    @staticmethod
    def _uids_match(observed: str, registered: str) -> bool:
        def normalize(value: str) -> str:
            return value.replace(" ", "").replace(":", "").upper()

        return normalize(observed) == normalize(registered)
