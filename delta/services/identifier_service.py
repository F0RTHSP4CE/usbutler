from fastapi import Depends, HTTPException, status

from database import JsonDatabase, get_database
from schemas import Identifier, IdentifierCreate, IdentifierUpdate


class IdentifierService:
    """Service layer for identifier operations."""

    COLLECTION = "identifiers"

    def __init__(self, db: JsonDatabase):
        self.db = db

    def get_all(self) -> list[Identifier]:
        """Get all identifiers."""
        identifiers_data = self.db.get_all(self.COLLECTION)
        return [Identifier(**identifier) for identifier in identifiers_data.values()]

    def get_by_id(self, identifier_id: str) -> Identifier:
        """Get an identifier by ID."""
        identifier_data = self.db.get_by_id(self.COLLECTION, identifier_id)
        if not identifier_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Identifier with id '{identifier_id}' not found",
            )
        return Identifier(**identifier_data)

    def get_by_value(self, value: str) -> Identifier | None:
        """Get an identifier by its value."""
        identifiers = self.db.find_by_field(self.COLLECTION, "value", value)
        if identifiers:
            return Identifier(**identifiers[0])
        return None

    def get_by_owner(self, owner_id: str) -> list[Identifier]:
        """Get all identifiers owned by a user."""
        identifiers = self.db.find_by_field(self.COLLECTION, "owner_id", owner_id)
        return [Identifier(**identifier) for identifier in identifiers]

    def create(self, identifier_data: IdentifierCreate) -> Identifier:
        """Create a new identifier."""
        # Check for duplicate value
        existing = self.get_by_value(identifier_data.value)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Identifier with value '{identifier_data.value}' already exists",
            )

        identifier_id = self.db.generate_id()
        identifier = Identifier(
            id=identifier_id,
            value=identifier_data.value,
            type=identifier_data.type,
            owner_id=identifier_data.owner_id,
            metadata=identifier_data.metadata,
        )
        self.db.create(self.COLLECTION, identifier_id, identifier.model_dump())
        return identifier

    def update(
        self, identifier_id: str, identifier_data: IdentifierUpdate
    ) -> Identifier:
        """Update an existing identifier."""
        existing = self.get_by_id(identifier_id)

        # Check for duplicate value if changing
        if identifier_data.value and identifier_data.value != existing.value:
            duplicate = self.get_by_value(identifier_data.value)
            if duplicate and duplicate.id != identifier_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Identifier with value '{identifier_data.value}' already exists",
                )

        update_data = identifier_data.model_dump(exclude_unset=True)
        updated_identifier = existing.model_copy(update=update_data)
        self.db.update(self.COLLECTION, identifier_id, updated_identifier.model_dump())
        return updated_identifier

    def delete(self, identifier_id: str) -> bool:
        """Delete an identifier."""
        # Ensure identifier exists
        self.get_by_id(identifier_id)
        return self.db.delete(self.COLLECTION, identifier_id)

    def assign_owner(self, identifier_id: str, owner_id: str | None) -> Identifier:
        """Assign or unassign an owner to an identifier."""
        identifier = self.get_by_id(identifier_id)
        identifier.owner_id = owner_id
        self.db.update(self.COLLECTION, identifier_id, identifier.model_dump())
        return identifier


def get_identifier_service(
    db: JsonDatabase = Depends(get_database),
) -> IdentifierService:
    """Dependency injection for IdentifierService."""
    return IdentifierService(db)
