"""Local date helper used by the myoracle MCP server."""

from __future__ import annotations

import datetime


def get_current_date() -> datetime.date:
    """Return today's date according to the local system clock."""
    return datetime.date.today()
