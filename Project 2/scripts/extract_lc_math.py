"""Extract the math-only subset of a Learning Commons Knowledge Graph export.

Reads data/raw/<export>/nodes.jsonl and relationships.jsonl (never modified) and
writes data/interim/<export>_math/ with:
  - nodes.jsonl          math nodes of the labels Gap Finder uses
  - relationships.jsonl  relationships whose two endpoints were both kept
  - summary.json         counts per label and relationship type

Usage: python -I scripts/extract_lc_math.py data/raw/learning_commons_v1.15.0
"""
import json
import sys
from collections import Counter
from pathlib import Path

SUBJECT = "Mathematics"
KEEP_LABELS = {
    "StandardsFramework",
    "StandardsFrameworkItem",
    "LearningComponent",
    "Misconception",
    "Construct",
    "Course",
    "LessonGrouping",
    "Lesson",
    "Activity",
    "Assessment",
}


def main(raw_dir: Path) -> None:
    out_dir = raw_dir.parent.parent / "interim" / f"{raw_dir.name}_math"
    out_dir.mkdir(parents=True, exist_ok=True)

    kept_ids = set()
    node_counts = Counter()
    with open(raw_dir / "nodes.jsonl", encoding="utf-8") as src, \
            open(out_dir / "nodes.jsonl", "w", encoding="utf-8") as dst:
        for line in src:
            rec = json.loads(line)
            label = rec["labels"][0]
            if label in KEEP_LABELS and rec["properties"].get("academicSubject") == SUBJECT:
                kept_ids.add(rec["identifier"])
                node_counts[label] += 1
                dst.write(line)

    rel_counts = Counter()
    with open(raw_dir / "relationships.jsonl", encoding="utf-8") as src, \
            open(out_dir / "relationships.jsonl", "w", encoding="utf-8") as dst:
        for line in src:
            rec = json.loads(line)
            if rec["source_identifier"] in kept_ids and rec["target_identifier"] in kept_ids:
                rel_counts[rec["label"]] += 1
                dst.write(line)

    summary = {
        "source": str(raw_dir),
        "filter": {"academicSubject": SUBJECT, "labels": sorted(KEEP_LABELS)},
        "nodes": dict(node_counts.most_common()),
        "relationships": dict(rel_counts.most_common()),
        "totals": {"nodes": sum(node_counts.values()), "relationships": sum(rel_counts.values())},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
