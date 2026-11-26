"""Client check-ins between sessions (내담자 수시 기록)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Keep in sync with the check constraint in 20261122000100_client_check_ins.sql and the client page.
CHECK_IN_EMOTIONS = ("불안", "슬픔", "화남", "무기력", "외로움", "긴장", "피곤함", "괜찮음", "편안함", "기쁨")
Emotion = Literal["불안", "슬픔", "화남", "무기력", "외로움", "긴장", "피곤함", "괜찮음", "편안함", "기쁨"]
# The consent text the client agrees to; bump when the text changes so old consents are distinguishable.
CLIENT_CONSENT_VERSION = "2026-11-22-draft"
INVITE_VALID_DAYS = 7


class CheckInCreate(BaseModel):
    mood: int = Field(ge=0, le=10)
    emotions: list[Emotion] = Field(default_factory=list, max_length=8)
    note: str = Field(default="", max_length=1000)

    @field_validator("emotions")
    @classmethod
    def _distinct(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @field_validator("note")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class CheckIn(BaseModel):
    id: str
    mood: int
    emotions: list[str] = Field(default_factory=list)
    note: str = ""
    created_at: str


class ClientLinkStatus(BaseModel):
    link_id: str
    status: Literal["invited", "active", "ended"]
    created_at: str | None = None
    invite_expires_at: str | None = None
    accepted_at: str | None = None
    ended_at: str | None = None


class ClientInviteResponse(BaseModel):
    """The token is returned once; only its hash is stored."""

    link_id: str
    token: str
    expires_at: str


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    consent_version: str = Field(min_length=1, max_length=40)


class ClientMe(BaseModel):
    linked: bool
    status: Literal["active", "ended"] | None = None
    consented_at: str | None = None
    consent_version: str = CLIENT_CONSENT_VERSION
