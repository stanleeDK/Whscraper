import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = (
    "https://www.whitehouse.gov/wp-content/themes/whitehouse/"
    "static-assets/flourish/flourish-geo-embed/map/"
)
INDEX_URL = BASE_URL + "index.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.whitehouse.gov/",
}


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wh_arrests (
            created_at DATE,
            data_period_start TEXT,
            data_period_end TEXT,
            city TEXT,
            state TEXT,
            arrests INTEGER,
            charges TEXT,
            origin_countries TEXT,
            gang_affiliation INTEGER
        )
    """)
    conn.commit()


def run_requests():
    out = Path("flourish_data") 
    print(f"Fetching: {INDEX_URL}")

    try:
        resp = requests.get(INDEX_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.HTTPError as e:
        print(f"  HTTP {e.response.status_code} — {INDEX_URL}")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"\nFailed — {e}\nThe server may be IP-restricted.")
        sys.exit(1)

    html = resp.text

    payload = re.search(r'_Flourish_data\s*=\s*(\{.*\})', html)
    if payload:
        data = json.loads(payload.group(1)) # only retrun the valid json, not the javacript variable holding it
        today = datetime.now().date()
        out.mkdir(parents=True, exist_ok=True)
        out_file = out / f"{today}_flourish_data.json"
        out_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"  Saved → {out_file}")

        events = data["events"]
        print(f"  {len(events)} events found")

        rows = []
        for event in events:
            metadata = event["metadata"]
            start_str, end_str = metadata[1].split(" - ")
            start_date = datetime.strptime(start_str, "%m/%d/%y").date()
            end_date = datetime.strptime(end_str, "%m/%d/%y").date()
            city, state = event["name"].split(", ", 1)
            rows.append((
                str(today),
                str(start_date),
                str(end_date),
                city,
                state,
                metadata[0],
                metadata[2],
                metadata[3],
                bool(metadata[4]),
            ))

        db_path = out / "wh_arrests.db"
        with sqlite3.connect(db_path) as conn:
            init_db(conn)
            conn.executemany("INSERT INTO wh_arrests VALUES (?,?,?,?,?,?,?,?,?)", rows)
            conn.commit()
        print(f"  Inserted {len(rows)} rows → {db_path}")
    else:
        print("  _Flourish_data not found in HTML")
        sys.exit(1)


if __name__ == "__main__":
    run_requests()
