"""
Daily scrape + email diff.
Run via cron: 0 7 * * * cd /path/to/Whscraper && uv run daily_check.py >> /var/log/whscraper.log 2>&1

Required env var:
  SENDGRID_API_KEY — your SendGrid API key
"""

import os
import subprocess
import sys
from datetime import datetime

import sendgrid
from sendgrid.helpers.mail import Mail

from diff_utils import FIELD_LABELS, diff_snapshots, list_snapshots, load_events, snapshot_date

EMAIL_TO    = "k.r.cooke@gmail.com"
EMAIL_FROM  = "info@stanlee.info"
WEB_APP_URL = "https://wh.stanlee.info"


def send_email(subject, body):
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        print("Missing SENDGRID_API_KEY — skipping email")
        return
    sg = sendgrid.SendGridAPIClient(api_key=api_key)
    message = Mail(from_email=EMAIL_FROM, to_emails=EMAIL_TO, subject=subject, plain_text_content=body)
    response = sg.send(message)
    print(f"Email sent: status {response.status_code}")


def build_email_body(prev_file, latest_file, changed, added, removed):
    lines = [f"Comparing {snapshot_date(prev_file)} → {snapshot_date(latest_file)}", ""]

    lines.append(f"Changed cities ({len(changed)}):")
    if changed:
        for entry in changed:
            lines.append(f"  {entry['name']}:")
            for field, (old_val, new_val) in entry["diffs"].items():
                label = FIELD_LABELS[field]
                lines.append(f"    {label}: {old_val} → {new_val}")
    else:
        lines.append("  None")

    lines.append("")
    lines.append(f"New cities ({len(added)}):")
    if added:
        for r in added:
            lines.append(f"  {r['name']} — {r['arrests']} arrests")
    else:
        lines.append("  None")

    lines.append("")
    lines.append(f"Removed cities ({len(removed)}):")
    if removed:
        for r in removed:
            lines.append(f"  {r['name']} — last known {r['arrests']} arrests")
    else:
        lines.append("  None")

    lines.append("")
    lines.append(f"See all changes here: {WEB_APP_URL}")

    return "\n".join(lines)


def main():
    print(f"[{datetime.now()}] Running scrape...")
    result = subprocess.run([sys.executable, "scrape_flourish_map.py"])
    if result.returncode != 0:
        print("Scrape failed — aborting")
        sys.exit(1)

    json_files = list_snapshots()
    if len(json_files) < 2:
        print("Only one snapshot on disk — nothing to diff")
        return

    prev_file, latest_file = json_files[-2], json_files[-1]
    print(f"Diffing {prev_file.name} vs {latest_file.name}")

    prev   = load_events(prev_file)
    latest = load_events(latest_file)
    changed, added, removed = diff_snapshots(prev, latest)

    if not (changed or added or removed):
        print("No changes detected — no email sent")
        return

    print(f"Changes: {len(changed)} changed, {len(added)} added, {len(removed)} removed")
    subject = f"WH Arrests — changes detected ({snapshot_date(latest_file)} vs {snapshot_date(prev_file)})"
    body = build_email_body(prev_file, latest_file, changed, added, removed)
    send_email(subject, body)


if __name__ == "__main__":
    main()
