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
        "select counts.*, sysdate as as_of from (select count(*) as staging, "
        "count(case when serial_match = 0 and rf_match = 0 then 1 end) as eligible, "
        "count(case when serial_match = 1 then 1 end) as serial_match, "
        "count(case when serial_match = 0 and rf_match = 1 then 1 end) as rf_conflict, "
        "min(case when serial_match = 0 and rf_match = 0 then LAST_TEST_DATE end) as oldest from ("
        "select s.LAST_TEST_DATE, "
        "case when exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES g "
        "where g.UUT_SERIAL_NUMBER = s.UUT_SERIAL_NUMBER) then 1 else 0 end as serial_match, "
        "case when exists (select 1 from ATE_RESULTS.GLOBAL_UUT_ATTRIBUTES g2 "
        "where g2.RF_NUMBER = s.RF_NUMBER) then 1 else 0 end as rf_match "
        f"from TRANSFER_USER.{staging_table} s)) counts"
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
        return None


def backlog_age_hours(oldest: Any, now: datetime | None = None) -> float | None:
    """Return the age of the oldest eligible row in hours, if known."""
    parsed = _parse_oldest(oldest)
    if parsed is None:
        return None
    reference = now or datetime.now()
    try:
        return (reference - parsed).total_seconds() / 3600.0
    except TypeError:
        return None


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
    if eligible <= 0:
        return False
    if eligible >= count_threshold:
        return True
    reference = now or _parse_oldest(entry.get("as_of"))
    age = backlog_age_hours(entry.get("oldest"), reference)
    return age is not None and age >= age_hours_threshold


def fetch_site_backlog(cursor: Any, site_name: str) -> dict[str, Any]:
    """Run the backlog query for one site and return its counts."""
    sql, binds = backlog_sql(site_name)
    cursor.execute(sql, binds) if binds else cursor.execute(sql)
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"Backlog query returned no result for {site_name}.")
    staging, eligible, serial_match, rf_conflict, oldest, as_of = row
    oldest_value = oldest.isoformat() if hasattr(oldest, "isoformat") else oldest
    as_of_value = as_of.isoformat() if hasattr(as_of, "isoformat") else as_of
    return {
        "site": site_name,
        "staging": int(staging or 0),
        "eligible": int(eligible or 0),
        "serial_match": int(serial_match or 0),
        "rf_conflict": int(rf_conflict or 0),
        "oldest": oldest_value,
        "as_of": as_of_value,
    }


def fetch_all_backlogs(cursor: Any) -> dict[str, dict[str, Any]]:
    """Return backlog entries keyed by site name."""
    return {site: fetch_site_backlog(cursor, site) for site in SITE_STAGING_TABLES}
