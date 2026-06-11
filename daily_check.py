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

from app import DB_PATH, get_db, get_diff

EMAIL_TO   = "stanleylee13@yahoo.com"
EMAIL_FROM = "info@stanlee.info"


def send_email(subject, body):
    api_key = os.environ.get("SENDGRID_API_KEY")

    if not api_key:
        print("Missing SENDGRID_API_KEY — skipping email")
        return

    sg = sendgrid.SendGridAPIClient(api_key=api_key)
    message = Mail(from_email=EMAIL_FROM, to_emails=EMAIL_TO, subject=subject, plain_text_content=body)
    response = sg.send(message)
    print(f"Email sent: status {response.status_code}")


def build_email_body(latest_date, prev_date, changed, added, removed):
    lines = [f"Comparing {prev_date} → {latest_date}", ""]

    lines.append(f"Arrest count changes ({len(changed)}):")
    if changed:
        for r in changed:
            sign = "+" if r["diff"] > 0 else ""
            lines.append(f"  {r['city']}, {r['state']}: {r['prev_arrests']} → {r['new_arrests']} ({sign}{r['diff']})")
    else:
        lines.append("  None")

    lines.append("")
    lines.append(f"New cities ({len(added)}):")
    if added:
        for r in added:
            lines.append(f"  {r['city']}, {r['state']} — {r['arrests']} arrests")
    else:
        lines.append("  None")

    lines.append("")
    lines.append(f"Removed cities ({len(removed)}):")
    if removed:
        for r in removed:
            lines.append(f"  {r['city']}, {r['state']} — last known {r['arrests']} arrests")
    else:
        lines.append("  None")

    return "\n".join(lines)


def main():
    print(f"[{datetime.now()}] Running scrape...")
    result = subprocess.run([sys.executable, "scrape_flourish_map.py"])
    if result.returncode != 0:
        print("Scrape failed — aborting")
        sys.exit(1)

    conn = get_db()
    latest_date, prev_date, changed, added, removed = get_diff(conn)
    conn.close()

    if prev_date is None:
        print("Only one scrape date in DB — nothing to diff")
        return

    has_changes = changed or added or removed
    if not has_changes:
        print("No changes detected — no email sent")
        return

    print(f"Changes detected: {len(changed)} arrest changes, {len(added)} added, {len(removed)} removed")
    subject = f"WH Arrests — changes detected ({latest_date} vs {prev_date})"
    body = build_email_body(latest_date, prev_date, changed, added, removed)
    send_email(subject, body)


def test_email():
    send_email("WH Arrests — test email", "This is a test email from daily_check.py.")


if __name__ == "__main__":
    main()
