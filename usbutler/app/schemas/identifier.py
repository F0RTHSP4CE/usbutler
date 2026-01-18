"""Identifier schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.identifier import IdentifierType


class IdentifierBase(BaseModel):
    """Base schema for identifier data."""

    value: str
    type: IdentifierType


class IdentifierCreate(IdentifierBase):
    """Schema for creating an identifier."""

    user_id: Optional[int] = None


class IdentifierUpdate(BaseModel):
    """Schema for updating an identifier."""

    value: Optional[str] = None
    type: Optional[IdentifierType] = None
    user_id: Optional[int] = None


class IdentifierResponse(IdentifierBase):
    """Schema for identifier response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None


class UserBrief(BaseModel):
    """Brief user info for identifier response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    status: str


class IdentifierWithUser(IdentifierResponse):
    """Schema for identifier response with user details."""

    user: Optional[UserBrief] = None


class LastScanResponse(BaseModel):
    """Schema for last scan response."""

    value: Optional[str] = None
    type: Optional[IdentifierType] = None
    scanned_at: Optional[datetime] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
