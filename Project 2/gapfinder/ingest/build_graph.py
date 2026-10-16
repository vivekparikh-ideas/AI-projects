"""Build graph-ready files from the interim data (decisions.md #11, #13, #14).

Reads:
  - data/interim/learning_commons_v1.15.0_math/   standards, crosswalks, Coherence Map, skill components
  - data/interim/im_first_edition_pilot/          first-edition lessons and verified answer keys
Writes data/processed/graph/nodes.jsonl and rels.jsonl, one row per node or relationship:
  {"label": ..., "id": ..., "props": {...}}  and  {"type": ..., "from": ..., "to": ..., "props": {...}}

Scope: current math frameworks, K-8 standards. Eedi misconceptions are left out until they are
linked to US standards (decisions.md #11).

Usage: uv run python -m gapfinder.ingest.build_graph
"""
import json
from collections import Counter

from gapfinder.config import CCSS_JURISDICTION, CCSS_NOTICE, IM_PILOT, K8_GRADES, LC_MATH, PROCESSED_GRAPH

LC_SOURCE = "https://cdn.learningcommons.org/knowledge-graph/v1.15.0/exports/"
REL_TYPES = {
    "hasChild": "HAS_CHILD",
    "hasStandardAlignment": "CROSSWALKS_TO",
    "buildsTowards": "BUILDS_TOWARDS",
    "relatesTo": "RELATES_TO",
    "supports": "SUPPORTS",
}


def grades(props: dict) -> list[str]:
    raw = props.get("gradeLevel") or "[]"
    try:
        values = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        values = [raw]
    return [str(v).strip() for v in values]


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def main() -> None:
    PROCESSED_GRAPH.mkdir(parents=True, exist_ok=True)
    lc_nodes = {r["identifier"]: r for r in read_jsonl(LC_MATH / "nodes.jsonl")}
    lc_rels = list(read_jsonl(LC_MATH / "relationships.jsonl"))

    current = {i for i, r in lc_nodes.items()
               if r["labels"][0] == "StandardsFramework" and r["properties"].get("isCurrent") == "true"}
    parent = {r["target_identifier"]: r["source_identifier"] for r in lc_rels if r["label"] == "hasChild"}

    def framework_of(i: str) -> str:
        for _ in range(50):
            if i not in parent:
                break
            i = parent[i]
        return i

    nodes, keep = [], set()
    for i, r in lc_nodes.items():
        label, p = r["labels"][0], r["properties"]
        common = {"license": p.get("license"), "attribution": p.get("attributionStatement"),
                  "source": LC_SOURCE, "provider": p.get("author")}
        if label == "StandardsFramework" and i in current:
            is_ccss = p.get("jurisdiction") == CCSS_JURISDICTION
            nodes.append({"label": "Framework", "id": i, "props": {
                "name": p.get("name"), "jurisdiction": p.get("jurisdiction"), "is_ccss": is_ccss,
                "v2_allowed": "ccss_commercial_license" if is_ccss else "pending_state_review", **common}})
            keep.add(i)
        elif label == "StandardsFrameworkItem":
            fw = framework_of(i)
            g = grades(p)
            if fw not in current or (g and not set(g) & K8_GRADES):
                continue
            is_ccss = p.get("jurisdiction") == CCSS_JURISDICTION
            nodes.append({"label": "Standard", "id": i, "props": {
                "code": p.get("statementCode"), "text": p.get("description"), "grades": g,
                "statement_type": p.get("normalizedStatementType") or p.get("statementType"),
                "jurisdiction": p.get("jurisdiction"), "framework_id": fw, "is_ccss": is_ccss,
                "notice": CCSS_NOTICE if is_ccss else None,
                "v2_allowed": "ccss_commercial_license" if is_ccss else "pending_state_review", **common}})
            keep.add(i)
        elif label == "LearningComponent":
            nodes.append({"label": "SkillComponent", "id": i, "props": {
                "text": p.get("description"), "v2_allowed": "yes", **common}})
            keep.add(i)

    rels = []
    for r in lc_rels:
        t = REL_TYPES.get(r["label"])
        s, e = r["source_identifier"], r["target_identifier"]
        if not t or s not in keep or e not in keep:
            continue
        p = r["properties"]
        props = {"license": p.get("license"), "attribution": p.get("attributionStatement"), "provider": p.get("author")}
        if t == "CROSSWALKS_TO":
            props |= {"jaccard": float(p["jaccard"]) if p.get("jaccard") else None,
                      "shared_components": p.get("sharedLCCount")}
        rels.append({"type": t, "from": s, "to": e, "props": props})

    ccss_by_code = {n["props"]["code"]: n["id"] for n in nodes
                    if n["label"] == "Standard" and n["props"]["is_ccss"] and n["props"]["code"]}
    unmatched = Counter()

    for lesson in read_jsonl(IM_PILOT / "lessons.jsonl"):
        nodes.append({"label": "Lesson", "id": lesson["id"], "props": {
            k: lesson.get(k) for k in ("title", "grade", "unit", "lesson", "section", "url", "edition", "license", "attribution")
        } | {"v2_allowed": "yes"}})
        for field, t in (("addressing", "ADDRESSES"), ("building_on", "BUILDS_ON"), ("building_towards", "PREPARES_FOR")):
            for code in lesson.get(field, []):
                if code in ccss_by_code:
                    rels.append({"type": t, "from": lesson["id"], "to": ccss_by_code[code], "props": {}})
                else:
                    unmatched[code] += 1

    for part in read_jsonl(IM_PILOT / "answer_keys_verified.jsonl"):
        nodes.append({"label": "Problem", "id": part["part_id"], "props": {
            "problem_id": part["problem_id"], "text": part["part_text"], "kind": part["kind"],
            "answer_key": part["answer_key"], "answer_source": part["answer_source"], "grade": part["grade"],
            "source_url": part["source_url"], "standard_verified": part["standard_verified"],
            "verified_by": part["verified_by"], "verified_at": part["verified_at"], "verification": part["verification"],
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "attribution": "Based on IM® K–12 Math authored by Illustrative Mathematics and licensed under CC BY 4.0. "
                           "Adapted: split into parts; answer keys derived by Gap Finder.",
            "checkable": True, "v2_allowed": "yes"}})
        code = part["standard"]
        if code in ccss_by_code:
            rels.append({"type": "ASSESSES", "from": part["part_id"], "to": ccss_by_code[code], "props": {}})
        else:
            unmatched[code] += 1

    with open(PROCESSED_GRAPH / "nodes.jsonl", "w", encoding="utf-8") as f:
        for n in nodes:
            f.write(json.dumps(n, ensure_ascii=False) + "\n")
    with open(PROCESSED_GRAPH / "rels.jsonl", "w", encoding="utf-8") as f:
        for r in rels:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {"nodes": dict(Counter(n["label"] for n in nodes)), "rels": dict(Counter(r["type"] for r in rels)),
               "total_nodes": len(nodes), "total_rels": len(rels), "unmatched_ccss_codes": dict(unmatched)}
    (PROCESSED_GRAPH / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
