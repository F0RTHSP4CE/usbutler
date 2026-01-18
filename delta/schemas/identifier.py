from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class IdentifierType(str, Enum):
    UID = "UID"
    PAN = "PAN"


class IdentifierBase(BaseModel):
    value: str = Field(..., min_length=1, description="Identifier value (UID or PAN)")
    type: IdentifierType = Field(..., description="Type of identifier")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class IdentifierCreate(IdentifierBase):
    """Schema for creating a new identifier."""

    owner_id: str | None = Field(None, description="Owner user ID")


class IdentifierUpdate(BaseModel):
    """Schema for updating an existing identifier."""

    value: str | None = Field(None, min_length=1)
    type: IdentifierType | None = None
    owner_id: str | None = None
    metadata: dict | None = None


class Identifier(IdentifierBase):
    """Full identifier model stored in database."""

    id: str = Field(..., description="Unique identifier ID")
    owner_id: str | None = Field(None, description="Owner user ID")

    model_config = ConfigDict(from_attributes=True)


class IdentifierResponse(BaseModel):
    """Response schema for a single identifier."""

    success: bool = True
    data: Identifier


class IdentifierListResponse(BaseModel):
    """Response schema for a list of identifiers."""

    success: bool = True
    data: list[Identifier]
    total: int
