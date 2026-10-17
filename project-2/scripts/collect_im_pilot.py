"""Download the public IM K-12 Math first-edition pages for the fractions pilot.

Rules (decisions.md #10, #16; IM Terms of Use §9):
  - public pages only: GET requests to im.kendallhunt.com, no cookies, never /oauth or login
  - one request every 2 seconds; every page is cached and never fetched twice
  - a page is kept only if it carries the CC BY 4.0 notice and no NonCommercial notice

Pilot scope:
  - K-5 grades 3-5: every unit's practice page (filtered to *.NF problems when parsed)
  - 6-8 grade 6, unit 4 (dividing fractions): every lesson's index and practice page,
    plus the index page of any lesson a practice problem says it came from

Writes raw HTML to data/raw/im_first_edition/<url path> and appends to fetch_log.jsonl.

Usage: uv run python scripts/collect_im_pilot.py
"""
import hashlib
import json
import re
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HOST = "https://im.kendallhunt.com"
ALLOWED_PREFIXES = ("/k5/teachers/", "/MS/teachers/")
USER_AGENT = "GapFinder-research/0.1 (open-source education project; low-rate, public pages only)"
DELAY_SECONDS = 2.0
K5_GRADES = ("grade-3", "grade-4", "grade-5")
# Fraction units: their lesson pages give the standards for section practice problems.
K5_FRACTION_UNITS = (("grade-3", 5), ("grade-4", 2), ("grade-4", 3), ("grade-5", 2), ("grade-5", 3), ("grade-5", 6))
MS_UNITS = (("1", "4"),)  # (grade 6 course id, unit)

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "im_first_edition"
LOG = RAW_DIR / "fetch_log.jsonl"

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT
_last_request = 0.0


def license_status(html: str) -> str:
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    if re.search(r"NonCommercial|NonCommerical|BY-NC", text):
        return "noncommercial"
    if re.search(r"Creative Commons Attribution 4\.0|CC BY 4\.0", text):
        return "cc-by-4.0"
    return "missing"


def known_missing() -> set[str]:
    """URLs that already returned 404, so they are not requested again."""
    if not LOG.exists():
        return set()
    with open(LOG, encoding="utf-8") as f:
        return {e["url"] for e in map(json.loads, f) if e["status"] == 404}


def fetch(path: str) -> str | None:
    """Return the page HTML from cache or from the site. None if unavailable or not CC BY."""
    global _last_request
    if not path.startswith(ALLOWED_PREFIXES) or "oauth" in path or "login" in path:
        raise ValueError(f"refusing to fetch {path}")
    target = RAW_DIR / path.lstrip("/")
    if HOST + path in known_missing():
        return None
    if target.exists():
        html = target.read_text(encoding="utf-8")
        return html if license_status(html) == "cc-by-4.0" else None

    wait = DELAY_SECONDS - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    resp = session.get(HOST + path, timeout=30, allow_redirects=False)
    _last_request = time.monotonic()

    entry = {"url": HOST + path, "status": resp.status_code, "retrieved": date.today().isoformat()}
    html = None
    if resp.status_code == 200:
        html = resp.text
        entry["license"] = license_status(html)
        entry["sha256"] = hashlib.sha256(resp.content).hexdigest()
        entry["bytes"] = len(resp.content)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"{resp.status_code} {entry.get('license', '-'):<13} {path}")
    if html is None or entry["license"] != "cc-by-4.0":
        return None
    return html


def links(html: str, pattern: str) -> list[str]:
    found = {a["href"] for a in BeautifulSoup(html, "html.parser").find_all("a", href=True)}
    return sorted(h for h in found if re.fullmatch(pattern, h))


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for grade in K5_GRADES:
        units_html = fetch(f"/k5/teachers/{grade}/units.html")
        if units_html is None:
            continue
        for lessons_path in links(units_html, rf"/k5/teachers/{grade}/unit-\d+/lessons\.html"):
            fetch(lessons_path.replace("lessons.html", "practice.html"))

    for grade, unit in K5_FRACTION_UNITS:
        lessons_html = fetch(f"/k5/teachers/{grade}/unit-{unit}/lessons.html")
        if lessons_html is None:
            continue
        pattern = rf"/k5/teachers/{grade}/unit-{unit}/lesson-\d+/preparation\.html"
        for prep_path in sorted(links(lessons_html, pattern), key=lambda p: int(p.split("lesson-")[1].split("/")[0])):
            fetch(prep_path.replace("preparation.html", "lesson.html"))

    for course, unit in MS_UNITS:
        unit_html = fetch(f"/MS/teachers/{course}/{unit}/index.html")
        if unit_html is None:
            continue
        lesson_dirs = {p.rsplit("/", 1)[0] for p in links(unit_html, rf"/MS/teachers/{course}/{unit}/\d+/preparation\.html")}
        referenced = set()
        for lesson_dir in sorted(lesson_dirs, key=lambda p: int(p.rsplit("/", 1)[1])):
            fetch(f"{lesson_dir}/index.html")
            practice = fetch(f"{lesson_dir}/practice.html")
            if practice:
                for u, l in re.findall(r"\(From Unit (\d+), Lesson (\d+)\.\)", practice):
                    referenced.add(f"/MS/teachers/{course}/{u}/{l}")
        for lesson_dir in sorted(referenced - lesson_dirs):
            fetch(f"{lesson_dir}/index.html")

    pages = sum(1 for p in RAW_DIR.rglob("*.html"))
    print(f"\n{pages} cached pages in {RAW_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
