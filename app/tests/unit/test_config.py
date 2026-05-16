"""Settings module: defaults + env-override behaviour."""

import pytest

from nbio.config import Settings

_KNOBS = ["DB_PATH", "BABY_NAME", "TZ", "DUP_WINDOW_SECONDS", "SSE_REPLAY_CAP"]


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every Settings-mapped env var so defaults are observable."""
    for k in _KNOBS:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_defaults(clean_env):
    """Constructed with no env file or env vars → schema defaults stand."""
    s = Settings(_env_file=None)
    assert s.db_path == "/data/app.db"
    assert s.baby_name == "Baby"
    assert s.tz == "Europe/London"
    assert s.dup_window_seconds == 120
    assert s.sse_replay_cap == 500


def test_env_override(clean_env):
    """Settings reads env vars by un-prefixed field name."""
    clean_env.setenv("BABY_NAME", "Newton")
    clean_env.setenv("DB_PATH", "/tmp/other.db")
    clean_env.setenv("TZ", "Pacific/Auckland")
    clean_env.setenv("DUP_WINDOW_SECONDS", "300")
    clean_env.setenv("SSE_REPLAY_CAP", "100")
    s = Settings(_env_file=None)
    assert s.baby_name == "Newton"
    assert s.db_path == "/tmp/other.db"
    assert s.tz == "Pacific/Auckland"
    assert s.dup_window_seconds == 300
    assert s.sse_replay_cap == 100


def test_unknown_env_ignored(clean_env):
    """`extra='ignore'` means stray env vars don't raise."""
    clean_env.setenv("TOTALLY_UNRELATED_KNOB", "nope")
    Settings(_env_file=None)


def test_singleton_importable():
    """The module-level singleton exists and has the expected types."""
    from nbio.config import settings

    assert isinstance(settings.dup_window_seconds, int)
    assert isinstance(settings.sse_replay_cap, int)
