"""Identifier schemas."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, computed_field
from app.models.identifier import (
    IdentifierState,
    IdentifierType,
    UidRotationOutcome,
    UidRotationProtocol,
)
from app.utils.masking import mask_identifier


class IdentifierCreate(BaseModel):
    value: str
    type: IdentifierType
    user_id: int


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
    chain_root_id: Optional[int] = None
    predecessor_id: Optional[int] = None
    state: IdentifierState = IdentifierState.STATIC
    generated_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    last_write_attempt_at: Optional[datetime] = None

    @computed_field
    @property
    def masked_value(self) -> str:
        return mask_identifier(self.value)


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    status: str
    uid_rotation_enabled: bool


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


class UidRotationAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    chain_root_id: int
    source_identifier_id: int
    target_reservation_id: int
    attempted_at: datetime
    protocol: UidRotationProtocol
    outcome: UidRotationOutcome
    detail: Optional[str] = None
    confirmed_at: Optional[datetime] = None


class IdentifierLineageResponse(BaseModel):
    root_id: int
    user_id: Optional[int] = None
    last_write_attempt_at: Optional[datetime] = None
    identifiers: List[IdentifierResponse]
    attempts: List[UidRotationAttemptResponse]
