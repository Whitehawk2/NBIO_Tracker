from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal["breast", "formula", "wee", "poo"]
FeedSide = Literal["L", "R", "both"]


class EventCreate(BaseModel):
    type: EventType
    occurred_at: str  # ISO-8601 UTC
    feed_side: FeedSide | None = None
    feed_duration_min: int | None = Field(default=None, ge=0, le=600)
    poo_quality: int | None = Field(default=None, ge=1, le=7)
    notes: str | None = Field(default=None, max_length=500)
    # Formula-only: brand name (e.g. "Materna") and volume in ml (cc).
    formula_brand: str | None = Field(default=None, max_length=40)
    formula_volume_ml: int | None = Field(default=None, ge=1, le=500)
    idempotency_key: str = Field(min_length=8, max_length=64)
    created_by_device: str = Field(min_length=1, max_length=64)
    skip_dup_check: bool = False


class EventPatch(BaseModel):
    occurred_at: str | None = None
    feed_side: FeedSide | None = None
    feed_duration_min: int | None = Field(default=None, ge=0, le=600)
    poo_quality: int | None = Field(default=None, ge=1, le=7)
    notes: str | None = Field(default=None, max_length=500)
    formula_brand: str | None = Field(default=None, max_length=40)
    formula_volume_ml: int | None = Field(default=None, ge=1, le=500)


class DeviceUpsert(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
