"""Pydantic model validation — every boundary of every field."""

import pytest
from pydantic import ValidationError

from nbio.models import (
    Actor,
    AppSettingsUpdate,
    BabyUpdate,
    DeviceUpsert,
    EventCreate,
    EventPatch,
)

VALID_EVENT = {
    "type": "breast",
    "occurred_at": "2026-05-16T03:00:00.000Z",
    "idempotency_key": "abcdefgh",
    "created_by_device": "device-1",
}


class TestEventCreate:
    def test_minimal_valid(self):
        e = EventCreate(**VALID_EVENT)
        assert e.type == "breast"
        assert e.feed_side is None
        assert e.feed_duration_min is None
        assert e.poo_quality is None
        assert e.notes is None
        assert e.skip_dup_check is False

    @pytest.mark.parametrize("t", ["breast", "formula", "wee", "poo"])
    def test_type_literals(self, t):
        EventCreate(**{**VALID_EVENT, "type": t})

    def test_type_rejects_other(self):
        with pytest.raises(ValidationError):
            EventCreate(**{**VALID_EVENT, "type": "snack"})

    @pytest.mark.parametrize("side", ["L", "R", "both"])
    def test_feed_side_literals(self, side):
        EventCreate(**{**VALID_EVENT, "feed_side": side})

    def test_feed_side_rejects_other(self):
        with pytest.raises(ValidationError):
            EventCreate(**{**VALID_EVENT, "feed_side": "left"})

    @pytest.mark.parametrize("dur", [0, 1, 300, 600])
    def test_feed_duration_bounds_ok(self, dur):
        EventCreate(**{**VALID_EVENT, "feed_duration_min": dur})

    @pytest.mark.parametrize("dur", [-1, 601, 9999])
    def test_feed_duration_bounds_reject(self, dur):
        with pytest.raises(ValidationError):
            EventCreate(**{**VALID_EVENT, "feed_duration_min": dur})

    @pytest.mark.parametrize("q", [1, 4, 7])
    def test_poo_quality_bounds_ok(self, q):
        EventCreate(**{**VALID_EVENT, "poo_quality": q})

    @pytest.mark.parametrize("q", [0, 8, -1])
    def test_poo_quality_bounds_reject(self, q):
        with pytest.raises(ValidationError):
            EventCreate(**{**VALID_EVENT, "poo_quality": q})

    def test_notes_max_length(self):
        EventCreate(**{**VALID_EVENT, "notes": "x" * 500})
        with pytest.raises(ValidationError):
            EventCreate(**{**VALID_EVENT, "notes": "x" * 501})

    @pytest.mark.parametrize("key_len", [8, 32, 64])
    def test_idem_key_length_ok(self, key_len):
        EventCreate(**{**VALID_EVENT, "idempotency_key": "x" * key_len})

    @pytest.mark.parametrize("key_len", [0, 7, 65])
    def test_idem_key_length_reject(self, key_len):
        with pytest.raises(ValidationError):
            EventCreate(**{**VALID_EVENT, "idempotency_key": "x" * key_len})

    def test_created_by_device_min_length(self):
        with pytest.raises(ValidationError):
            EventCreate(**{**VALID_EVENT, "created_by_device": ""})

    def test_skip_dup_check_default_false(self):
        assert EventCreate(**VALID_EVENT).skip_dup_check is False

    def test_skip_dup_check_explicit_true(self):
        assert EventCreate(**{**VALID_EVENT, "skip_dup_check": True}).skip_dup_check is True


class TestEventPatch:
    def test_empty_patch(self):
        p = EventPatch()
        assert p.model_dump(exclude_unset=True) == {}

    def test_partial_patch_only_includes_set(self):
        p = EventPatch(feed_side="R")
        assert p.model_dump(exclude_unset=True) == {"feed_side": "R"}

    def test_full_patch(self):
        p = EventPatch(
            occurred_at="2026-05-16T03:00:00.000Z",
            feed_side="both",
            feed_duration_min=20,
            poo_quality=5,
            notes="ok",
        )
        d = p.model_dump(exclude_unset=True)
        assert set(d) == {"occurred_at", "feed_side", "feed_duration_min", "poo_quality", "notes"}

    def test_bounds_apply(self):
        with pytest.raises(ValidationError):
            EventPatch(feed_duration_min=-1)
        with pytest.raises(ValidationError):
            EventPatch(poo_quality=8)
        with pytest.raises(ValidationError):
            EventPatch(notes="x" * 501)


class TestDeviceUpsert:
    def test_minimal(self):
        d = DeviceUpsert(color="#aabbcc")
        assert d.name is None
        assert d.color == "#aabbcc"


class TestBabyUpdate:
    def test_empty_is_valid_no_op(self):
        b = BabyUpdate()
        assert b.model_dump(exclude_unset=True) == {}

    def test_name_only(self):
        b = BabyUpdate(name="Mai")
        assert b.name == "Mai"
        assert b.dob is None

    def test_dob_iso_date(self):
        b = BabyUpdate(dob="2026-04-20")
        assert b.dob == "2026-04-20"

    @pytest.mark.parametrize("bad", ["2026", "26-04-20", "2026/04/20", "2026-4-20", "not-a-date"])
    def test_dob_rejects_non_iso_format(self, bad):
        with pytest.raises(ValidationError):
            BabyUpdate(dob=bad)

    def test_rejects_long_name(self):
        with pytest.raises(ValidationError):
            BabyUpdate(name="x" * 41)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            BabyUpdate(name="Mai", colour="blue")


class TestAppSettingsUpdate:
    def test_empty_is_valid_no_op(self):
        s = AppSettingsUpdate()
        assert s.model_dump(exclude_unset=True) == {}

    @pytest.mark.parametrize("tz", ["UTC", "Europe/London", "Asia/Jerusalem", "America/New_York"])
    def test_tz_accepts_valid_iana_zones(self, tz):
        s = AppSettingsUpdate(tz=tz)
        assert s.tz == tz

    @pytest.mark.parametrize("bad", ["NotAZone", "Europe/Atlantis", "GMT+5"])
    def test_tz_rejects_invalid_zone(self, bad):
        with pytest.raises(ValidationError):
            AppSettingsUpdate(tz=bad)

    def test_tz_none_means_use_env_default(self):
        s = AppSettingsUpdate(tz=None)
        assert s.tz is None

    def test_notes_md_max_length(self):
        AppSettingsUpdate(notes_md="x" * 2000)  # at boundary
        with pytest.raises(ValidationError):
            AppSettingsUpdate(notes_md="x" * 2001)


class TestActor:
    def test_default_kind_is_device(self):
        a = Actor(id="dev-1")
        assert a.kind == "device"
        assert a.name is None
        assert a.color is None

    def test_anonymous_actor(self):
        a = Actor(id="anon", kind="anonymous")
        assert a.kind == "anonymous"

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValidationError):
            Actor(id="dev-1", kind="user")  # not in scope this PR

    def test_with_name(self):
        DeviceUpsert(color="#aabbcc", name="Mum")

    @pytest.mark.parametrize("color", ["#000000", "#FFFFFF", "#abcdef", "#ABCDEF", "#123456"])
    def test_color_valid(self, color):
        DeviceUpsert(color=color)

    @pytest.mark.parametrize(
        "color",
        ["aabbcc", "#abc", "#aabbccdd", "#GGGGGG", "rgb(0,0,0)", "", "#1234567"],
    )
    def test_color_invalid(self, color):
        with pytest.raises(ValidationError):
            DeviceUpsert(color=color)

    def test_name_max_length(self):
        DeviceUpsert(color="#000000", name="x" * 40)
        with pytest.raises(ValidationError):
            DeviceUpsert(color="#000000", name="x" * 41)
