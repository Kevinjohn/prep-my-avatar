"""UTC helpers that preserve the application's historical naive-DB contract."""
from datetime import datetime, timezone


def utcnow():
    """Current UTC as a naive datetime for existing SQLite DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcfromtimestamp(timestamp):
    return datetime.fromtimestamp(float(timestamp), timezone.utc).replace(tzinfo=None)
