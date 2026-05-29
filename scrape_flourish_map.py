"""
Extracts the underlying data from the White House Flourish geo-embed map.

Run this from your OWN machine — the whitehouse.gov server IP-allowlists requests.

Two modes:
  python scrape_flourish_map.py          # requests-based (fast, may need cookies)
  python scrape_flourish_map.py --browser  # Playwright headless browser (most reliable)

Install deps:
  pip install requests beautifulsoup4 playwright
  playwright install chromium
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

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

# Well-known Flourish static data-file paths to probe
CANDIDATE_PATHS = [
    "data.csv", "data.json",
    "points.csv", "points.json",
    "regions.csv", "regions.json",
    "binding.json", "state.json",
    "template.yml",
]

OUTPUT_DIR = Path("flourish_data")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def save(name: str, content: bytes, suffix: str, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}{suffix}"
    path.write_bytes(content)
    print(f"  Saved → {path}")
    return path


def extract_inline_data(html: str) -> dict:
    """Pull Flourish data objects embedded directly in the page HTML/JS."""
    found = {}
    patterns = [
        r"window\._?[Ff]lourish(?:_data|\.data)\s*=\s*(\{.*?\});",
        r"var\s+flourishData\s*=\s*(\{.*?\});",
        r'"data"\s*:\s*(\[.*?\])',
    ]
    for pat in patterns:
        for m in re.finditer(pat, html, re.DOTALL):
            try:
                found[f"inline_{pat[:20]}"] = json.loads(m.group(1))
                print(f"  Found inline data block: {pat[:50]}")
            except json.JSONDecodeError:
                pass

    # GeoJSON / row-data assigned to any variable
    for m in re.finditer(r'(\w+)\s*=\s*(\{[^;]{200,}\})\s*;', html, re.DOTALL):
        snippet = m.group(2)
        if any(k in snippet for k in ('"features"', '"coordinates"', '"points"', '"rows"')):
            try:
                obj = json.loads(snippet)
                found[m.group(1)] = obj
                print(f"  Found geo-like inline object: {m.group(1)}")
            except json.JSONDecodeError:
                pass

    return found


def discover_data_urls(html: str, base: str) -> list[str]:
    urls: list[str] = []
    soup = BeautifulSoup(html, "html.parser")

    for attr in ("src", "href", "data-src", "data-url"):
        for tag in soup.find_all(attrs={attr: True}):
            val = tag[attr]
            if any(val.endswith(ext) for ext in (".json", ".csv", ".geojson", ".tsv")):
                urls.append(urljoin(base, val))

    for m in re.finditer(r'["\']([^"\']+\.(?:json|csv|geojson|tsv))["\']', html):
        candidate = m.group(1)
        urls.append(candidate if candidate.startswith("http") else urljoin(base, candidate))

    return list(dict.fromkeys(urls))


# ---------------------------------------------------------------------------
# Mode 1: requests-based
# ---------------------------------------------------------------------------

def fetch(url: str, session: requests.Session) -> requests.Response | None:
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp
    except requests.HTTPError as e:
        print(f"  HTTP {e.response.status_code} — {url}")
    except requests.RequestException as e:
        print(f"  Error — {url}: {e}")
    return None


def run_requests():
    session = requests.Session()
    out = OUTPUT_DIR / "requests"

    print(f"Fetching: {INDEX_URL}")
    resp = fetch(INDEX_URL, session)
    if resp is None:
        print(
            "\nFailed. The server may be IP-restricted.\n"
            "Try --browser mode or run from a browser-based machine."
        )
        sys.exit(1)

    html = resp.text
    (out / "index.html").parent.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    print(f"  index.html saved ({len(html):,} chars)")

    print("\nScanning for inline data...")
    inline = extract_inline_data(html)
    for key, data in inline.items():
        p = out / f"inline_{key[:40].replace('/', '_')}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"  Saved → {p}")

    print("\nDiscovering + fetching data files...")
    data_urls = discover_data_urls(html, BASE_URL)
    data_urls += [BASE_URL + c for c in CANDIDATE_PATHS]
    data_urls = [u for u in dict.fromkeys(data_urls)
                 if any(u.endswith(e) for e in (".json", ".csv", ".geojson", ".tsv"))]

    found = 0
    for url in data_urls:
        print(f"  GET {url}")
        r = fetch(url, session)
        if r is None:
            continue
        found += 1
        name = Path(urlparse(url).path).stem
        suffix = Path(urlparse(url).path).suffix or ".bin"
        save(name, r.content, suffix, out)
        if suffix == ".csv":
            lines = r.text.splitlines()
            print(f"    {len(lines)} rows  |  header: {lines[0][:100]}")
        elif suffix == ".json":
            try:
                obj = r.json()
                print(f"    JSON keys: {list(obj.keys())[:8] if isinstance(obj, dict) else f'array[{len(obj)}]'}")
            except Exception:
                pass

    if found == 0 and not inline:
        print("\nNo data files found via static requests.")
        print("Run again with --browser to capture dynamic network traffic.")

    print(f"\nOutput: {out.resolve()}/")


# ---------------------------------------------------------------------------
# Mode 2: Playwright headless browser (intercepts all network requests)
# ---------------------------------------------------------------------------

def run_browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run:")
        print("  pip install playwright && playwright install chromium")
        sys.exit(1)

    out = OUTPUT_DIR / "browser"
    out.mkdir(parents=True, exist_ok=True)
    captured: dict[str, bytes] = {}

    def handle_response(response):
        url = response.url
        if any(url.endswith(ext) for ext in (".json", ".csv", ".geojson", ".tsv", ".js")):
            try:
                body = response.body()
                captured[url] = body
                print(f"  Captured: {url}  ({len(body):,} bytes)")
            except Exception:
                pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            extra_http_headers={"Referer": "https://www.whitehouse.gov/"},
            user_agent=HEADERS["User-Agent"],
        )
        page = context.new_page()
        page.on("response", handle_response)

        print(f"Loading: {INDEX_URL}")
        page.goto(INDEX_URL, wait_until="networkidle", timeout=60_000)

        # Save the final rendered HTML
        html = page.content()
        (out / "index.html").write_text(html, encoding="utf-8")
        print(f"  Rendered HTML saved ({len(html):,} chars)")

        # Give extra time for lazy-loaded data
        page.wait_for_timeout(3000)
        browser.close()

    print(f"\nProcessing {len(captured)} captured network responses...")
    data_files = {
        url: body for url, body in captured.items()
        if any(url.endswith(e) for e in (".json", ".csv", ".geojson", ".tsv"))
    }

    if not data_files:
        # Scan JS files for embedded data
        for url, body in captured.items():
            if url.endswith(".js"):
                text = body.decode("utf-8", errors="replace")
                inline = extract_inline_data(text)
                for key, data in inline.items():
                    p_path = out / f"from_js_{key[:40]}.json"
                    p_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                    print(f"  Extracted from JS → {p_path}")

    for url, body in data_files.items():
        name = Path(urlparse(url).path).stem
        suffix = Path(urlparse(url).path).suffix or ".bin"
        saved = save(name, body, suffix, out)
        if suffix == ".csv":
            text = body.decode("utf-8", errors="replace")
            lines = text.splitlines()
            print(f"    {len(lines)} rows  |  header: {lines[0][:100]}")
        elif suffix == ".json":
            try:
                obj = json.loads(body)
                print(f"    JSON keys: {list(obj.keys())[:8] if isinstance(obj, dict) else f'array[{len(obj)}]'}")
            except Exception:
                pass

    print(f"\nOutput: {out.resolve()}/")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract data from White House Flourish map")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Use Playwright headless browser (handles JS-rendered pages and Cloudflare)",
    )
    args = parser.parse_args()

    if args.browser:
        run_browser()
    else:
        run_requests()
