"""
Shared helpers for reading flourish JSON snapshots and diffing them.
Used by both daily_check.py (email alerts) and app.py (web UI).
"""

import json
from pathlib import Path

DATA_DIR = Path("flourish_data")

# Maps internal field keys → human-readable labels used in email/web output.
FIELD_LABELS = {
    "arrests":     "arrests",
    "date_range":  "date range",
    "charges":     "charges",
    "countries":   "countries",
    "gang":        "gang affiliation",
}


def list_snapshots() -> list[Path]:
    """Return all snapshot files sorted oldest → newest (filenames are ISO-dated)."""
    return sorted(DATA_DIR.glob("*_flourish_data.json"))


def snapshot_date(path: Path) -> str:
    """Extract the ISO date from a snapshot filename, e.g. '2026-06-16'."""
    return path.stem.replace("_flourish_data", "")


def load_events(path: Path) -> dict:
    """Return a dict keyed by city name from a flourish JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    result = {}
    for event in data.get("events", []):
        meta = event.get("metadata", [])
        result[event["name"]] = {
            "arrests":    meta[0] if len(meta) > 0 else None,
            "date_range": meta[1] if len(meta) > 1 else None,
            "charges":    meta[2] if len(meta) > 2 else None,
            "countries":  meta[3] if len(meta) > 3 else None,
            "gang":       meta[4] if len(meta) > 4 else None,
        }
    return result


def unique_countries(events: dict) -> set:
    """Return the set of distinct origin countries across all cities in a snapshot."""
    countries = set()
    for fields in events.values():
        for c in (fields.get("countries") or "").split(","):
            c = c.strip()
            if c:
                countries.add(c)
    return countries


def diff_snapshots(prev: dict, latest: dict):
    """
    Compare two snapshots and return (changed, added, removed).

    Both `prev` and `latest` are dicts produced by load_events(), shaped like:
        {
            "Laredo, TX":  {"arrests": 5921, "date_range": "01/21/25 - 05/28/26",
                            "charges": "Assault, Drugs, ...", "countries": "MEXICO, CUBA",
                            "gang": "✅"},
            ...
        }
    """
    prev_keys   = set(prev)
    latest_keys = set(latest)

    # Cities in latest but not prev — brand new entries.
    added = []
    for city_name in sorted(latest_keys - prev_keys):
        entry = {"name": city_name}
        entry.update(latest[city_name])
        added.append(entry)

    # Cities in prev but gone from latest — removed entries.
    removed = []
    for city_name in sorted(prev_keys - latest_keys):
        entry = {"name": city_name}
        entry.update(prev[city_name])
        removed.append(entry)

    # Cities in both — collect field-level differences.
    changed = []
    for city_name in sorted(prev_keys & latest_keys):
        old_data = prev[city_name]
        new_data = latest[city_name]

        field_diffs = {}
        for field in FIELD_LABELS:
            old_val = old_data[field]
            new_val = new_data[field]
            if old_val != new_val:
                field_diffs[field] = (old_val, new_val)

        if field_diffs:
            changed.append({"name": city_name, "diffs": field_diffs})

    return changed, added, removed
