from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

EventType = Literal["breast", "formula", "wee", "poo", "vitd", "tummy_time"]
FeedSide = Literal["L", "R", "both"]
# Future-auth seam: today `device` is the only kind. When session/JWT
# auth lands, add `"user"` to this Literal; the rest of the app keeps
# its `Depends(current_actor)` signature.
ActorKind = Literal["device", "anonymous"]


class EventCreate(BaseModel):
    type: EventType
    occurred_at: str  # ISO-8601 UTC
    feed_side: FeedSide | None = None
    feed_duration_min: int | None = Field(default=None, ge=0, le=600)
    # Sub-minute precision for tummy time (timer). When set, takes
    # precedence over feed_duration_min in displays; aggregations
    # COALESCE(sec, min*60). Range 0..36000s (10h) to cover any
    # plausible session.
    feed_duration_sec: int | None = Field(default=None, ge=0, le=36000)
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
    feed_duration_sec: int | None = Field(default=None, ge=0, le=36000)
    poo_quality: int | None = Field(default=None, ge=1, le=7)
    notes: str | None = Field(default=None, max_length=500)
    formula_brand: str | None = Field(default=None, max_length=40)
    formula_volume_ml: int | None = Field(default=None, ge=1, le=500)


class DeviceUpsert(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class BabyUpdate(BaseModel):
    """PATCH payload for the singleton babies row (id=1)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=40)
    # ISO-8601 date (YYYY-MM-DD). Time-of-day deliberately omitted —
    # birth time isn't useful for the auto-age display, and a calendar
    # date input is friendlier than a datetime picker.
    dob: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class AppSettingsUpdate(BaseModel):
    """PATCH payload for the singleton app_settings row (id=1)."""

    model_config = ConfigDict(extra="forbid")

    # NULL = use process-level config.tz from .env. A non-null value
    # overrides for bucketing + display until cleared.
    tz: str | None = Field(default=None)
    notes_md: str | None = Field(default=None, max_length=2000)

    @field_validator("tz")
    @classmethod
    def _tz_must_be_known(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"unknown timezone: {v!r}") from e
        return v


class GrowthCreate(BaseModel):
    """POST payload for /api/growth. weight_g is required in v1.1.1.

    length_mm and head_circ_mm are accepted (forward-compat with #55)
    but not exposed in the UI yet — they round-trip through the DB.
    """

    measured_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    weight_g: int = Field(ge=0, le=30000)
    length_mm: int | None = Field(default=None, ge=0, le=2000)
    head_circ_mm: int | None = Field(default=None, ge=0, le=1000)
    notes: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=64)
    created_by_device: str = Field(min_length=1, max_length=64)


class GrowthPatch(BaseModel):
    """PATCH payload — all fields optional, only present ones update."""

    measured_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    weight_g: int | None = Field(default=None, ge=0, le=30000)
    length_mm: int | None = Field(default=None, ge=0, le=2000)
    head_circ_mm: int | None = Field(default=None, ge=0, le=1000)
    notes: str | None = Field(default=None, max_length=500)


class Actor(BaseModel):
    """
    The requestor as resolved by `auth.current_actor`. Today only
    kind='device' (looked up via X-Device-Id header) or kind='anonymous'
    (header missing or device unknown). Future auth widens this to
    'user' without changing route signatures.
    """

    id: str
    kind: ActorKind = "device"
    name: str | None = None
    color: str | None = None
