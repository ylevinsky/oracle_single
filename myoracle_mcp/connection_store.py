"""Saved Oracle connection paths, document loading, and site name resolution."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent

# Human / agent labels → saved connection keys in ``.db/connections.json``.
_SITE_ALIASES: dict[str, tuple[str, ...]] = {
    "RH": ("rh", "repair", "repair center", "repair-center", "repair_center"),
    "HUN": ("hun", "hungary", "orclhun"),
    "FLEX": ("flex", "ofakim"),
    "PH": ("ph", "philippines", "ionics"),
    "DWH": ("dwh", "flexdwh"),
    "DWH_CL": ("dwh-cl", "dwh cl", "dwhcl", "dwh_cl"),
    "es_db2_orclsp_sys": ("spain", "orclsp", "es-db2-sp", "es_db2"),
}


def repository_root() -> Path:
    override = os.environ.get("MYORACLE_REPOSITORY_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    return _DEFAULT_ROOT


def connections_file() -> Path:
    override = os.environ.get("MYORACLE_CONNECTIONS_FILE", "").strip()
    if override:
        return Path(override).resolve()
    return repository_root() / ".db" / "connections.json"


def connections_example_file() -> Path:
    return repository_root() / ".db" / "connections.json.example"


def _normalize_label(label: str) -> str:
    return " ".join(str(label or "").strip().lower().replace("_", " ").split())


def resolve_connection_name(
    connection_name: str, connections: dict[str, Any]
) -> str:
    """Map site labels (e.g. ``rh``, ``repair center``) to saved connection keys."""
    raw = str(connection_name or "").strip()
    if not raw:
        raise ValueError("connection_name must not be empty")

    if raw in connections:
        return raw

    normalized = _normalize_label(raw)
    oracle_keys = {
        name
        for name, details in connections.items()
        if isinstance(details, dict)
        and str(details.get("engine", "")).lower() == "oracle"
    }

    for key in oracle_keys:
        if _normalize_label(key) == normalized:
            return key

    for key, aliases in _SITE_ALIASES.items():
        if key not in oracle_keys:
            continue
        if normalized == _normalize_label(key) or normalized in aliases:
            return key

    available = ", ".join(sorted(oracle_keys)) or "(none)"
    raise ValueError(
        f"Unknown connection '{connection_name}'. "
        f"Saved Oracle connections: {available}. "
        f"Repair Center is saved as 'RH' — call connections_list or oracle_sites_index."
    )


def load_connections_document() -> dict[str, Any]:
    """Read ``connections.json``, optionally bootstrapping from the example file."""
    path = connections_file()
    if not path.is_file():
        example = connections_example_file()
        if example.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(example, path)
        else:
            raise ValueError(
                f"Connection file not found: {path}. "
                f"Copy {example.name} to connections.json and fill credentials."
            )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document


def oracle_site_index(connections: dict[str, Any]) -> list[dict[str, Any]]:
    """Return site metadata for agents that do not read connections.json directly."""
    rows: list[dict[str, Any]] = []
    for key in sorted(connections):
        details = connections.get(key)
        if not isinstance(details, dict):
            continue
        if str(details.get("engine", "")).lower() != "oracle":
            continue
        aliases = list(_SITE_ALIASES.get(key, ()))
        rows.append(
            {
                "connection_name": key,
                "aliases": aliases,
                "host": str(details.get("host", "")),
                "database": str(details.get("database", "")),
                "sid": str(details.get("sid") or details.get("database", "")),
            }
        )
    return rows