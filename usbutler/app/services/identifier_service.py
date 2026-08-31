"""Identifier service for database operations."""

from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models.identifier import Identifier, IdentifierState, IdentifierType
from app.models.user import User
from app.schemas.identifier import IdentifierCreate, IdentifierUpdate


class IdentifierService:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self, skip: int = 0, limit: int = 100) -> List[Identifier]:
        stmt = (
            select(Identifier)
            .options(selectinload(Identifier.user))
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def get_by_id(self, identifier_id: int) -> Optional[Identifier]:
        stmt = (
            select(Identifier)
            .options(selectinload(Identifier.user))
            .where(Identifier.id == identifier_id)
        )
        return self.db.scalars(stmt).first()

    def get_by_value(self, value: str) -> Optional[Identifier]:
        stmt = (
            select(Identifier)
            .options(selectinload(Identifier.user))
            .where(func.lower(Identifier.value) == value.lower())
        )
        return self.db.scalars(stmt).first()

    def create(self, data: IdentifierCreate) -> Identifier:
        from app.services.uid_rotation_service import (
            UidCollisionError,
            UidRotationService,
            normalize_uid,
        )

        rotation = UidRotationService(self.db)
        value = (
            normalize_uid(data.value) if data.type == IdentifierType.UID else data.value
        )
        if data.type == IdentifierType.UID and rotation.is_reserved(value):
            raise UidCollisionError("UID was used or reserved previously")
        identifier = Identifier(value=value, type=data.type, user_id=data.user_id)
        self.db.add(identifier)
        self.db.flush()
        user = self.db.get(User, data.user_id)
        rotation.register_identifier(
            identifier,
            bool(user and user.uid_rotation_enabled and settings.UID_ROTATION_ENABLED),
        )
        self.db.commit()
        self.db.refresh(identifier)
        return identifier

    def update(
        self, identifier_id: int, data: IdentifierUpdate
    ) -> Optional[Identifier]:
        identifier = self.get_by_id(identifier_id)
        if not identifier:
            return None
        if identifier.chain_root_id:
            from app.services.uid_rotation_service import LineageMutationError

            raise LineageMutationError(
                "Rotating UID lineage nodes cannot be edited individually"
            )
        from app.services.uid_rotation_service import (
            UidCollisionError,
            UidRotationService,
            normalize_uid,
        )

        rotation = UidRotationService(self.db)
        old_type, old_value = identifier.type, identifier.value
        for k, v in data.model_dump(exclude_unset=True).items():
            if (
                k == "value"
                and v
                and (data.type or identifier.type) == IdentifierType.UID
            ):
                v = normalize_uid(v)
                if v.lower() != identifier.value.lower() and rotation.is_reserved(v):
                    raise UidCollisionError("UID was used or reserved previously")
            setattr(identifier, k, v)
        if identifier.type == IdentifierType.UID and (
            old_type != IdentifierType.UID
            or identifier.value.lower() != old_value.lower()
        ):
            identifier.reservation_id = None
            user = self.db.get(User, identifier.user_id) if identifier.user_id else None
            rotation.register_identifier(
                identifier,
                bool(
                    user and user.uid_rotation_enabled and settings.UID_ROTATION_ENABLED
                ),
            )
        elif identifier.type != IdentifierType.UID:
            identifier.reservation_id = None
            identifier.state = IdentifierState.STATIC
        self.db.commit()
        self.db.refresh(identifier)
        return identifier

    def delete(self, identifier_id: int) -> bool:
        identifier = self.get_by_id(identifier_id)
        if not identifier:
            return False
        if identifier.chain_root_id:
            from app.services.uid_rotation_service import LineageMutationError

            raise LineageMutationError(
                "Delete the complete rotating UID lineage instead"
            )
        self.db.delete(identifier)
        self.db.commit()
        return True

    def assign_to_user(
        self, identifier_id: int, user_id: Optional[int]
    ) -> Optional[Identifier]:
        identifier = self.get_by_id(identifier_id)
        if not identifier:
            return None
        if identifier.chain_root_id:
            from app.services.uid_rotation_service import LineageMutationError

            raise LineageMutationError(
                "Assign the complete rotating UID lineage instead"
            )
        from app.services.uid_rotation_service import UidRotationService

        user = self.db.get(User, user_id) if user_id else None
        UidRotationService(self.db).ensure_policy_for_assignment(
            identifier, user, initialize_candidates=settings.UID_ROTATION_ENABLED
        )
        self.db.commit()
        self.db.refresh(identifier)
        return identifier

    def assign_lineage(
        self, root_id: int, user_id: Optional[int]
    ) -> Optional[Identifier]:
        identifier = self.get_by_id(root_id)
        if not identifier or identifier.chain_root_id != identifier.id:
            return None
        from app.services.uid_rotation_service import UidRotationService

        user = self.db.get(User, user_id) if user_id else None
        UidRotationService(self.db).ensure_policy_for_assignment(
            identifier, user, initialize_candidates=settings.UID_ROTATION_ENABLED
        )
        self.db.commit()
        self.db.refresh(identifier)
        return identifier

    def get_lineage(self, root_id: int) -> Optional[dict]:
        from app.services.uid_rotation_service import UidRotationService

        return UidRotationService(self.db).get_lineage(root_id)

    def delete_lineage(self, root_id: int) -> bool:
        from app.services.uid_rotation_service import UidRotationService

        return UidRotationService(self.db).delete_lineage(root_id)
