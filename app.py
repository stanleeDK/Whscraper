import sqlite3
import subprocess
import sys
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for

app = Flask(__name__)

DB_PATH = Path("flourish_data/wh_arrests.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_diff(conn):
    """Compare the two most recent scrape dates. Returns (latest, prev, changed, added, removed)."""
    dates = conn.execute(
        "SELECT DISTINCT created_at FROM wh_arrests ORDER BY created_at DESC LIMIT 2"
    ).fetchall()

    if len(dates) < 2:
        latest_date = dates[0]["created_at"] if dates else None
        return latest_date, None, [], [], []

    latest_date = dates[0]["created_at"]
    prev_date   = dates[1]["created_at"]

    changed = conn.execute("""
        SELECT l.city, l.state, p.arrests AS prev_arrests, l.arrests AS new_arrests,
               l.arrests - p.arrests AS diff
        FROM wh_arrests l
        JOIN wh_arrests p ON l.city = p.city AND l.state = p.state AND p.created_at = ?
        WHERE l.created_at = ? AND l.arrests != p.arrests
        ORDER BY ABS(l.arrests - p.arrests) DESC
    """, (prev_date, latest_date)).fetchall()

    added = conn.execute("""
        SELECT city, state, arrests FROM wh_arrests WHERE created_at = ?
        AND (city || '|' || state) NOT IN (
            SELECT city || '|' || state FROM wh_arrests WHERE created_at = ?
        )
        ORDER BY city
    """, (latest_date, prev_date)).fetchall()

    removed = conn.execute("""
        SELECT city, state, arrests FROM wh_arrests WHERE created_at = ?
        AND (city || '|' || state) NOT IN (
            SELECT city || '|' || state FROM wh_arrests WHERE created_at = ?
        )
        ORDER BY city
    """, (prev_date, latest_date)).fetchall()

    return latest_date, prev_date, changed, added, removed


@app.route("/")
def summary():
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(DISTINCT created_at) AS scrape_count, COUNT(DISTINCT city) AS city_count FROM wh_arrests"
    ).fetchone()
    all_countries = conn.execute("SELECT origin_countries FROM wh_arrests").fetchall()
    latest_date, prev_date, changed, added, removed = get_diff(conn)
    conn.close()

    unique_countries = {
        c.strip()
        for r in all_countries
        for c in (r["origin_countries"] or "").split(",")
        if c.strip()
    }

    return render_template(
        "summary.html",
        scrape_count=row["scrape_count"],
        city_count=row["city_count"],
        country_count=len(unique_countries),
        latest_date=latest_date,
        prev_date=prev_date,
        changed=changed or [],
        added=added or [],
        removed=removed or [],
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
