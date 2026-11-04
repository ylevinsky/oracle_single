"""Per-site eligible staging backlog for the Spain Repair Center sync.

A staging row is eligible when its serial AND its RF number are both absent
from ``ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES``. Serial matches and RF conflicts
are classified separately so an operator can tell a true backlog from a
duplicate-key block. The queue (``TRANSFER_PRODUCTS_QUEUE``) is deliberately
not part of this query: it is a liveness hint, not a completeness record.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

SITE_STAGING_TABLES = {
    "Ofakim": "OFAKIM_UUT_ATTRUBUTES_1",
    "Hungary": "HUNGARY_UUT_ATTRUBUTES",
    "RH": "RH_UUT_ATTRUBUTES",
    "PH": "PH_UUT_ATTRUBUTES",
}

BACKLOG_COUNT_THRESHOLD = 100
BACKLOG_AGE_HOURS = 24


def backlog_sql(site_name: str) -> tuple[str, dict[str, Any]]:
    """Return the backlog query and binds for one site staging table."""
    try:
        staging_table = SITE_STAGING_TABLES[site_name]
    except KeyError as exc:
        raise ValueError(f"Unknown backlog site: {site_name!r}.") from exc
    sql = (
        "select "
        f"(select count(*) from TRANSFER_USER.{staging_table}) as staging, "
        f"(select count(*) from TRANSFER_USER.{staging_table} s "
        "where not exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES g "
        "where g.UUT_SERIAL_NUMBER = s.UUT_SERIAL_NUMBER) "
        "and not exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES g2 "
        "where g2.RF_NUMBER = s.RF_NUMBER)) as eligible, "
        f"(select count(*) from TRANSFER_USER.{staging_table} s "
        "where exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES g "
        "where g.UUT_SERIAL_NUMBER = s.UUT_SERIAL_NUMBER)) as serial_match, "
        f"(select count(*) from TRANSFER_USER.{staging_table} s "
        "where not exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES g "
        "where g.UUT_SERIAL_NUMBER = s.UUT_SERIAL_NUMBER) "
        "and exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES g2 "
        "where g2.RF_NUMBER = s.RF_NUMBER)) as rf_conflict, "
        f"(select min(s.LAST_TEST_DATE) from TRANSFER_USER.{staging_table} s) as oldest "
        "from DUAL"
    )
    return sql, {}


def _parse_oldest(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(pattern)], pattern)
        except ValueError:
            continue
    return None


def backlog_age_hours(oldest: Any, now: datetime | None = None) -> float | None:
    """Return the age of the oldest eligible row in hours, if known."""
    parsed = _parse_oldest(oldest)
    if parsed is None:
        return None
    reference = now or datetime.now()
    return (reference - parsed).total_seconds() / 3600.0


def is_breach(
    entry: dict[str, Any],
    now: datetime | None = None,
    count_threshold: int = BACKLOG_COUNT_THRESHOLD,
    age_hours_threshold: float = BACKLOG_AGE_HOURS,
) -> bool:
    """Return whether one site backlog entry breaches count or age limits."""
    try:
        eligible = int(entry.get("eligible") or 0)
    except (TypeError, ValueError):
        eligible = 0
    if eligible >= count_threshold:
        return True
    age = backlog_age_hours(entry.get("oldest"), now)
    return age is not None and age >= age_hours_threshold


def fetch_site_backlog(cursor: Any, site_name: str) -> dict[str, Any]:
    """Run the backlog query for one site and return its counts."""
    sql, binds = backlog_sql(site_name)
    cursor.execute(sql, binds) if binds else cursor.execute(sql)
    row = cursor.fetchone()
    if row is None:
        staging, eligible, serial_match, rf_conflict, oldest = 0, 0, 0, 0, None
    else:
        staging, eligible, serial_match, rf_conflict, oldest = row
    if hasattr(oldest, "isoformat"):
        oldest_value: Any = oldest.isoformat()
    else:
        oldest_value = oldest
    return {
        "site": site_name,
        "staging": int(staging or 0),
        "eligible": int(eligible or 0),
        "serial_match": int(serial_match or 0),
        "rf_conflict": int(rf_conflict or 0),
        "oldest": oldest_value,
    }


def fetch_all_backlogs(cursor: Any) -> dict[str, dict[str, Any]]:
    """Return backlog entries keyed by site name."""
    return {site: fetch_site_backlog(cursor, site) for site in SITE_STAGING_TABLES}
