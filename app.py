import sqlite3
import subprocess
import sys
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for

from diff_utils import (
    FIELD_LABELS,
    diff_snapshots,
    list_snapshots,
    load_events,
    snapshot_date,
    unique_countries,
)

app = Flask(__name__)

DB_PATH = Path("flourish_data/wh_arrests.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def summary():
    snapshots = list_snapshots()

    # No data scraped yet.
    if not snapshots:
        return render_template(
            "summary.html",
            snapshot_count=0,
            latest_date=None,
            prev_date=None,
            city_count=0,
            country_count=0,
            changed=[], added=[], removed=[],
            field_labels=FIELD_LABELS,
        )

    latest_file = snapshots[-1]
    latest = load_events(latest_file)

    # Stats reflect the LATEST snapshot only.
    latest_date  = snapshot_date(latest_file)
    city_count   = len(latest)
    country_count = len(unique_countries(latest))

    # Diff requires at least two snapshots.
    changed, added, removed = [], [], []
    prev_date = None
    if len(snapshots) >= 2:
        prev_file = snapshots[-2]
        prev_date = snapshot_date(prev_file)
        changed, added, removed = diff_snapshots(load_events(prev_file), latest)

    return render_template(
        "summary.html",
        snapshot_count=len(snapshots),
        latest_date=latest_date,
        prev_date=prev_date,
        city_count=city_count,
        country_count=country_count,
        changed=changed,
        added=added,
        removed=removed,
        field_labels=FIELD_LABELS,
    )


@app.post("/run-scrape")
def run_scrape():
    subprocess.run([sys.executable, "scrape_flourish_map.py"], check=False)
    return redirect(url_for("summary"))


ALLOWED_SORT_COLS = {
    "created_at", "data_period_start", "data_period_end",
    "city", "state", "arrests", "charges", "origin_countries", "gang_affiliation",
}

@app.route("/arrests")
def arrests():
    sort = request.args.get("sort")
    direction = request.args.get("dir", "asc")

    if sort in ALLOWED_SORT_COLS and direction in ("asc", "desc"):
        order_clause = f"{sort} {direction.upper()}"
    else:
        sort, direction = None, None
        order_clause = "arrests DESC"

    conn = get_db()
    all_dates = [r["created_at"] for r in conn.execute(
        "SELECT DISTINCT created_at FROM wh_arrests ORDER BY created_at DESC"
    ).fetchall()]

    selected_date = request.args.get("date")
    if selected_date not in all_dates:
        selected_date = all_dates[0] if all_dates else None

    rows = conn.execute(
        f"""SELECT data_period_start, data_period_end, city, state,
                   arrests, charges, origin_countries, gang_affiliation
            FROM wh_arrests
            WHERE created_at = ?
            ORDER BY {order_clause}""",
        (selected_date,)
    ).fetchall()
    conn.close()
    return render_template("table.html", rows=rows, sort=sort, direction=direction,
                           all_dates=all_dates, selected_date=selected_date)


if __name__ == "__main__":
    # app.run(debug=True)
    app.run(host="127.0.0.1", port=8000)
