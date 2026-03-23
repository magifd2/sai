"""Timezone-aware timestamp utilities."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(tz=timezone.utc)


def from_unix(ts: float) -> datetime:
    """Convert a Unix timestamp (float) to a timezone-aware UTC datetime."""
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def to_unix(dt: datetime) -> float:
    """Convert a datetime to a Unix timestamp float."""
    return dt.timestamp()


def slack_ts_to_datetime(ts: str) -> datetime:
    """Convert a Slack message timestamp string (e.g. '1234567890.123456') to datetime."""
    return from_unix(float(ts))
