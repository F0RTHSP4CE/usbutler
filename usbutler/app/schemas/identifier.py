"""Identifier schemas."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, computed_field
from app.models.identifier import IdentifierType
from app.utils.masking import mask_identifier


class IdentifierCreate(BaseModel):
    value: str
    type: IdentifierType
    user_id: Optional[int] = None


class IdentifierUpdate(BaseModel):
    value: Optional[str] = None
    type: Optional[IdentifierType] = None
    user_id: Optional[int] = None


class IdentifierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    value: str
    type: IdentifierType
    user_id: Optional[int] = None

    @computed_field
    @property
    def masked_value(self) -> str:
        return mask_identifier(self.value)


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    status: str


class IdentifierWithUser(IdentifierResponse):
    user: Optional[UserBrief] = None


class LastScanResponse(BaseModel):
    value: Optional[str] = None
    type: Optional[IdentifierType] = None
    scanned_at: Optional[datetime] = None
    user_id: Optional[int] = None
    username: Optional[str] = None

    @computed_field
    @property
    def masked_value(self) -> str:
        return mask_identifier(self.value) if self.value else ""
