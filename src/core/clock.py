"""
Current time for database timestamps.

The schema stores UTC in `timestamp without time zone` columns, so this returns a naive UTC
datetime: the same value `datetime.utcnow()` gave, without its deprecation.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
