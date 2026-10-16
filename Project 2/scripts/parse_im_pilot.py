"""Parse the cached IM first-edition pilot pages into problem and lesson records.

Reads data/raw/im_first_edition/ (written by collect_im_pilot.py) and writes
data/interim/im_first_edition_pilot/:
  - problems.jsonl  one record per practice problem in the pilot standards
  - lessons.jsonl   grade 6 lessons with their Addressing / Building On / Building Towards standards
  - summary.json

Answer keys are not public, so every problem has answer_key = null (see decisions.md #16).

Usage: uv run python scripts/parse_im_pilot.py
"""
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup, Tag

HOST = "https://im.kendallhunt.com"
PILOT_PREFIXES = ("3.NF", "4.NF", "5.NF", "6.NS.A")
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
ATTRIBUTION = ("Based on IM® K–12 Math authored by Illustrative Mathematics and licensed under CC BY 4.0. "
               "Adapted: problem text extracted from the web page; answer keys are not IM's.")
EDITION = {"K5": "IM K–5 Math, first edition (© 2021 Illustrative Mathematics)",
           "MS": "IM 6–8 Math, first edition (© 2017–2019 Open Up Resources; © 2019 Illustrative Mathematics)"}

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "im_first_edition"
OUT_DIR = ROOT / "data" / "interim" / "im_first_edition_pilot"


def problem_text(content: Tag) -> tuple[str, list[dict]]:
    """Plain text with LaTeX kept and images replaced by their alt text."""
    content = BeautifulSoup(str(content), "html.parser")
    images = []
    for fig in content.find_all("figure"):
        img = fig.find("img", alt=True)
        desc = fig.select_one("[id^=dialog-long-description]")
        alt = img["alt"] if img else ""
        description = ""
        if desc:
            description = BeautifulSoup(desc.get_text(" "), "html.parser").get_text(" ")
            description = re.sub(r"^\s*Description:\s*", "", re.sub(r"\s+", " ", description)).strip()
        images.append({"src": img.get("src") if img else None, "alt": alt, "description": description})
        fig.replace_with(f" [image: {alt}] ")
    text = re.sub(r"[ \t\r\f\v]+", " ", content.get_text(" "))
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    return text, images


def lesson_standards(html: str) -> dict[str, list[str]]:
    """Union of the standards listed in every 'CCSS Standards' menu on a lesson page."""
    soup = BeautifulSoup(html, "html.parser")
    out = {"addressing": [], "building_on": [], "building_towards": []}
    for menu in soup.select("section.im-c-link-menu"):
        first = menu.find("p")
        if not first or "Standards" not in first.get_text():
            continue
        for heading in menu.select("p.im-c-hero__underline"):
            key = heading.get_text(strip=True).lower().replace(" ", "_")
            ul = heading.find_next_sibling("ul")
            if key in out and ul:
                for a in ul.find_all("a"):
                    code = a.get_text(strip=True)
                    if code not in out[key]:
                        out[key].append(code)
    return out


def k5_unit_lessons(lessons_html: Path) -> list[dict]:
    """Lessons of a K-5 unit in order, each with its section heading and standards."""
    m = re.search(r"grade-(\d)/unit-(\d+)/", lessons_html.as_posix())
    grade, unit = m.group(1), m.group(2)
    soup = BeautifulSoup(lessons_html.read_text(encoding="utf-8"), "html.parser")
    section, out, seen = None, [], set()
    for el in soup.find_all(["h4", "a"]):
        text = re.sub(r"\s+", " ", el.get_text(" ")).strip()
        if el.name == "h4" and re.match(r"Section [A-Z]:", text):
            section = text
        elif el.name == "a" and re.search(r"/lesson-(\d+)/preparation\.html$", el.get("href", "")) and text:
            number = re.search(r"/lesson-(\d+)/", el["href"]).group(1)
            if number in seen:
                continue
            seen.add(number)
            page = lessons_html.parent / f"lesson-{number}" / "lesson.html"
            stds = lesson_standards(page.read_text(encoding="utf-8")) if page.exists() else {}
            out.append({
                "id": f"im1e:k5:{grade}-{unit}-{number}",
                "grade": grade, "unit": unit, "lesson": number,
                "section": section,
                "title": re.sub(r"^\d+\s+|\s+PLC Activity$", "", text),
                **{k: stds.get(k, []) for k in ("addressing", "building_on", "building_towards")},
                "url": f"{HOST}/k5/teachers/grade-{grade}/unit-{unit}/lesson-{number}/lesson.html",
                "edition": EDITION["K5"], "license": LICENSE_URL, "attribution": ATTRIBUTION,
            })
    return out


def solution_id(problem_row: Tag) -> str | None:
    sol = problem_row.find_next_sibling("div", class_="im-c-row")
    link = sol.find("a", href=True) if sol else None
    m = re.search(r"practice_problem_(\d+)", link["href"]) if link else None
    return m.group(1) if m else None


def parse_practice_page(path: Path, lessons: dict, sections: dict) -> list[dict]:
    rel = "/" + path.relative_to(RAW_DIR).as_posix()
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    band = "K5" if rel.startswith("/k5/") else "MS"
    if band == "K5":
        m = re.match(r"/k5/teachers/grade-(\d)/unit-(\d+)/", rel)
        grade, unit, lesson = m.group(1), m.group(2), None
    else:
        m = re.match(r"/MS/teachers/(\d)/(\d+)/(\d+)/", rel)
        grade, unit, lesson = str(int(m.group(1)) + 5), m.group(2), m.group(3)

    records = []
    section = None
    for row in soup.find_all(lambda t: t.name in ("h2", "h3", "h4") or (
            t.name == "div" and {"im-c-row", "im-theme--green"} <= set(t.get("class", [])))):
        if row.name != "div":
            text = re.sub(r"\s+", " ", row.get_text(" ")).strip()
            if re.match(r"Section [A-Z]:", text):
                section = text
            continue
        heading = row.select_one(".im-c-row__aside h3")
        if not heading or not heading.get_text(strip=True).startswith("Problem"):
            continue
        content = row.select_one(".im-c-content")
        if content is None:
            continue
        text, images = problem_text(content)

        if band == "K5":
            label = row.find("strong", string=re.compile("Practicing Standards"))
            if label:
                standards = re.split(r"[,\s]+", label.parent.get_text(" ").split(":", 1)[1].strip())
                origin = {"section": "Pre-unit"}
                standards_source = "problem"
            else:
                standards = sections.get((grade, unit, section), [])
                origin = {"section": section}
                standards_source = "section_addressing"
        else:
            origin_text = row.find_next("span", class_="pp-aligned-lesson-address")
            m2 = re.search(r"From Unit (\d+), Lesson (\d+)", origin_text.get_text()) if origin_text else None
            src_unit, src_lesson = (m2.group(1), m2.group(2)) if m2 else (unit, lesson)
            origin = {"from_unit": src_unit, "from_lesson": src_lesson}
            standards = lessons.get((grade, src_unit, src_lesson), {}).get("addressing", [])
            standards_source = "lesson_addressing"

        standards = [s for s in standards if s]
        pid = solution_id(row)
        records.append({
            "id": f"im1e:pp:{pid}" if pid else f"im1e:{rel}#{heading.get_text(strip=True)}",
            "band": band,
            "grade": grade,
            "unit": unit,
            "lesson": lesson,
            "problem_label": heading.get_text(strip=True),
            "origin": origin,
            "standards": standards,
            "standards_source": standards_source,
            "text": text,
            "images": images,
            "has_image": bool(images),
            "answer_key": None,
            "answer_source": None,
            "solution_public": False,
            "source_url": HOST + rel,
            "edition": EDITION[band],
            "license": LICENSE_URL,
            "attribution": ATTRIBUTION,
            "v2_allowed": True,
            "retrieved": date.today().isoformat(),
        })
    return records


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    lessons = {}
    lesson_records = []
    for path in sorted(RAW_DIR.glob("MS/teachers/*/*/*/index.html")):
        course, unit, lesson = path.parts[-4:-1]
        grade = str(int(course) + 5)
        html = path.read_text(encoding="utf-8")
        stds = lesson_standards(html)
        lessons[(grade, unit, lesson)] = stds
        h1 = BeautifulSoup(html, "html.parser").find("h1")
        lesson_records.append({
            "id": f"im1e:ms:{course}-{unit}-{lesson}",
            "grade": grade, "unit": unit, "lesson": lesson,
            "title": h1.get_text(" ", strip=True) if h1 else None,
            **stds,
            "url": f"{HOST}/MS/teachers/{course}/{unit}/{lesson}/index.html",
            "edition": EDITION["MS"], "license": LICENSE_URL, "attribution": ATTRIBUTION,
        })

    sections = {}
    for path in sorted(RAW_DIR.glob("k5/teachers/grade-*/unit-*/lessons.html")):
        for lesson in k5_unit_lessons(path):
            lesson_records.append(lesson)
            key = (lesson["grade"], lesson["unit"], lesson["section"])
            sections.setdefault(key, [])
            sections[key] += [s for s in lesson["addressing"] if s not in sections[key]]

    problems = []
    for path in sorted(RAW_DIR.glob("**/practice.html")):
        problems.extend(parse_practice_page(path, lessons, sections))
    pilot = [p for p in problems if any(s.startswith(PILOT_PREFIXES) for s in p["standards"])]

    with open(OUT_DIR / "problems.jsonl", "w", encoding="utf-8") as f:
        for p in pilot:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with open(OUT_DIR / "lessons.jsonl", "w", encoding="utf-8") as f:
        for lesson in lesson_records:
            f.write(json.dumps(lesson, ensure_ascii=False) + "\n")

    by_std = Counter(s for p in pilot for s in p["standards"] if s.startswith(PILOT_PREFIXES))
    summary = {
        "problems_parsed": len(problems),
        "pilot_problems": len(pilot),
        "pilot_by_grade": dict(sorted(Counter(p["grade"] for p in pilot).items())),
        "pilot_with_images": sum(p["has_image"] for p in pilot),
        "pilot_by_standards_source": dict(Counter(p["standards_source"] for p in pilot)),
        "parsed_without_standards": sum(not p["standards"] for p in problems),
        "pilot_standards_covered": len(by_std),
        "problems_per_standard": dict(sorted(by_std.items())),
        "lessons": len(lesson_records),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
