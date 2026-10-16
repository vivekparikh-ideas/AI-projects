"""Build a small, committed test fixture from the math-only Learning Commons copy.

Scope: Common Core fraction standards for grades 4-6 (4.NF, 5.NF, 6.NS.A) plus
everything the agent touches around them:
  - Coherence Map neighbours (buildsTowards / relatesTo, 1 hop)
  - California standards crosswalked to them (hasStandardAlignment)
  - learning components that support them, IM lessons aligned to them
  - the hierarchy ancestors of every standard, up to its framework
  - a small Eedi sample (misconceptions + constructs), which is not linked to standards

Writes tests/fixtures/lc_math_sample/{nodes,relationships}.jsonl and ATTRIBUTION.md.

Usage: python -I scripts/make_fixture.py data/interim/learning_commons_v1.15.0_math
"""
import json
import sys
from pathlib import Path

SEED_PREFIXES = ("4.NF.", "5.NF.", "6.NS.A.")
STATE = "California"
EEDI_SAMPLE = 20
ATTRIBUTION_HEADER = """# Fixture attribution

This sample is derived from the Learning Commons Knowledge Graph v1.15.0 and is used for tests only.

Common Core State Standards: © Copyright 2010. National Governors Association Center for Best Practices
and Council of Chief State School Officers. All rights reserved.

Attribution statements carried by the records in this sample:
"""


def main(src: Path) -> None:
    project = Path(__file__).resolve().parent.parent
    out = project / "tests" / "fixtures" / "lc_math_sample"
    out.mkdir(parents=True, exist_ok=True)

    nodes = {}
    with open(src / "nodes.jsonl", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            nodes[rec["identifier"]] = rec
    rels = []
    with open(src / "relationships.jsonl", encoding="utf-8") as f:
        for line in f:
            rels.append(json.loads(line))

    def label(i):
        return nodes[i]["labels"][0]

    def prop(i, key):
        return nodes[i]["properties"].get(key)

    seeds = {
        i for i in nodes
        if label(i) == "StandardsFrameworkItem"
        and prop(i, "jurisdiction") == "Multi-State"
        and str(prop(i, "statementCode") or "").startswith(SEED_PREFIXES)
    }
    keep = set(seeds)

    for r in rels:
        s, t, lab = r["source_identifier"], r["target_identifier"], r["label"]
        if lab in ("buildsTowards", "relatesTo") and (s in seeds or t in seeds):
            keep.update((s, t))
    standards = {i for i in keep if label(i) == "StandardsFrameworkItem"}
    for r in rels:
        s, t, lab = r["source_identifier"], r["target_identifier"], r["label"]
        if lab == "hasStandardAlignment" and t in standards and prop(s, "jurisdiction") == STATE:
            keep.add(s)
        elif lab == "supports" and t in standards and label(s) == "LearningComponent":
            keep.add(s)
        elif lab == "hasEducationalAlignment" and t in standards and label(s) == "Lesson":
            keep.add(s)

    parent = {r["target_identifier"]: r["source_identifier"] for r in rels if r["label"] == "hasChild"}
    for i in [i for i in keep if label(i) == "StandardsFrameworkItem"]:
        while i in parent:
            i = parent[i]
            keep.add(i)

    eedi = sorted(i for i in nodes if label(i) == "Misconception")[:EEDI_SAMPLE]
    keep.update(eedi)
    for r in rels:
        if r["label"] == "hinders" and r["source_identifier"] in eedi:
            keep.add(r["target_identifier"])

    kept_rels = [r for r in rels if r["source_identifier"] in keep and r["target_identifier"] in keep]
    with open(out / "nodes.jsonl", "w", encoding="utf-8") as f:
        for i in sorted(keep):
            f.write(json.dumps(nodes[i], ensure_ascii=False) + "\n")
    with open(out / "relationships.jsonl", "w", encoding="utf-8") as f:
        for r in sorted(kept_rels, key=lambda r: r["identifier"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    statements = sorted({nodes[i]["properties"].get("attributionStatement", "") for i in keep}
                        | {r["properties"].get("attributionStatement", "") for r in kept_rels})
    with open(out / "ATTRIBUTION.md", "w", encoding="utf-8") as f:
        f.write(ATTRIBUTION_HEADER)
        for s in statements:
            if s:
                f.write(f"\n- {s}")
        f.write("\n")

    counts = {}
    for i in keep:
        counts[label(i)] = counts.get(label(i), 0) + 1
    rel_counts = {}
    for r in kept_rels:
        rel_counts[r["label"]] = rel_counts.get(r["label"], 0) + 1
    print(f"{len(keep)} nodes, {len(kept_rels)} relationships")
    print("nodes:", dict(sorted(counts.items(), key=lambda kv: -kv[1])))
    print("rels :", dict(sorted(rel_counts.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
