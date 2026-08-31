"""User schemas."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import UserStatus


class UserCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=100)
    status: UserStatus = UserStatus.ACTIVE
    allowed_sources: Optional[List[str]] = None
    mifare_rotation_enabled: bool = False


class UserUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: Optional[str] = Field(default=None, min_length=1, max_length=100)
    status: Optional[UserStatus] = None
    allowed_sources: Optional[List[str]] = None
    mifare_rotation_enabled: Optional[bool] = None


class IdentifierBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    value: str
    type: str
    last_used_at: Optional[datetime] = None


class IdentifierLookupRequest(BaseModel):
    value: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    status: UserStatus
    allowed_sources: List[str] = []
    mifare_rotation_enabled: bool


class UserWithIdentifiers(UserResponse):
    identifiers: List[IdentifierBrief] = []


class TokenResponse(BaseModel):
    token: str
    message: str = "Store this token securely. It will not be shown again."


class MifareRotationBulkUpdate(BaseModel):
    enabled: bool


class MifareRotationBulkResponse(BaseModel):
    enabled: bool
    updated_users: int
