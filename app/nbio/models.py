from typing import Literal, Optional

from pydantic import BaseModel, Field

EventType = Literal["feed", "wee", "poo"]
FeedSide = Literal["L", "R", "both"]


class EventCreate(BaseModel):
    type: EventType
    occurred_at: str  # ISO-8601 UTC
    feed_side: Optional[FeedSide] = None
    feed_duration_min: Optional[int] = Field(default=None, ge=0, le=600)
    poo_quality: Optional[int] = Field(default=None, ge=1, le=7)
    notes: Optional[str] = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=64)
    created_by_device: str = Field(min_length=1, max_length=64)
    skip_dup_check: bool = False


class EventPatch(BaseModel):
    occurred_at: Optional[str] = None
    feed_side: Optional[FeedSide] = None
    feed_duration_min: Optional[int] = Field(default=None, ge=0, le=600)
    poo_quality: Optional[int] = Field(default=None, ge=1, le=7)
    notes: Optional[str] = Field(default=None, max_length=500)


class DeviceUpsert(BaseModel):
    name: Optional[str] = Field(default=None, max_length=40)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
