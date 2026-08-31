"""UTC time helpers for SQLite-compatible naive timestamps."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return a naive datetime whose value is explicitly derived from UTC."""
    return datetime.now(UTC).replace(tzinfo=None)
