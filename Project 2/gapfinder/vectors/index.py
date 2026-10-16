"""Embed and upsert Gap Finder's text into Pinecone (decisions.md #3, #17).

Namespaces:
  - standards:   Common Core K-8 standards, plus the skill components that support them.
                 Used to match a homework problem to a Common Core standard.
  - curriculum:  verified problem parts and first-edition lessons (titles and sections for now).

Reads data/processed/graph/ (the same files loaded into Neo4j), so both stores hold the same ids.
Idempotent: upserting the same id overwrites it.

Usage: uv run python -m gapfinder.vectors.index
"""
import json
import time
from collections import defaultdict

from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone, ServerlessSpec

from gapfinder.config import PROCESSED_GRAPH, pinecone_settings

EMBED_MODEL = "text-embedding-3-small"
DIMENSIONS = 768
TEXT_LIMIT = 1000
BATCH = 100


def clean(meta: dict) -> dict:
    """Pinecone metadata accepts strings, numbers, booleans and lists of strings, never null."""
    out = {}
    for k, v in meta.items():
        if v is None or v == []:
            continue
        out[k] = v[:TEXT_LIMIT] if isinstance(v, str) else v
    return out


def build_records() -> dict[str, list[dict]]:
    nodes = {n["id"]: n for n in map(json.loads, open(PROCESSED_GRAPH / "nodes.jsonl", encoding="utf-8"))}
    rels = [json.loads(line) for line in open(PROCESSED_GRAPH / "rels.jsonl", encoding="utf-8")]
    ccss = {i: n["props"] for i, n in nodes.items()
            if n["label"] == "Standard" and n["props"]["is_ccss"] and n["props"]["statement_type"] == "Standard"}

    supports = defaultdict(set)
    assesses = {}
    for r in rels:
        if r["type"] == "SUPPORTS" and r["to"] in ccss:
            supports[r["from"]].add(r["to"])
        elif r["type"] == "ASSESSES":
            assesses[r["from"]] = nodes[r["to"]]["props"]["code"]

    records = defaultdict(list)
    for i, p in ccss.items():
        records["standards"].append({"id": i, "text": f"{p['code']}: {p['text']}", "metadata": clean({
            "kind": "standard", "codes": [p["code"]], "grades": p["grades"], "text": p["text"],
            "license": p["license"], "attribution": p["attribution"], "notice": p["notice"]})})
    for lc_id, standard_ids in supports.items():
        p = nodes[lc_id]["props"]
        codes = sorted(ccss[s]["code"] for s in standard_ids)
        grades = sorted({g for s in standard_ids for g in ccss[s]["grades"]})
        records["standards"].append({"id": lc_id, "text": p["text"], "metadata": clean({
            "kind": "skill_component", "codes": codes, "grades": grades, "text": p["text"],
            "license": p["license"], "attribution": p["attribution"]})})

    for i, n in nodes.items():
        p = n["props"]
        if n["label"] == "Problem":
            records["curriculum"].append({"id": i, "text": p["text"], "metadata": clean({
                "kind": "problem", "codes": [assesses[i]] if i in assesses else [], "grades": [p["grade"]],
                "text": p["text"], "source_url": p["source_url"], "license": p["license"], "attribution": p["attribution"]})})
        elif n["label"] == "Lesson":
            text = f"Grade {p['grade']}, unit {p['unit']}, lesson {p['lesson']}: {p['title']}"
            if p.get("section"):
                text += f" ({p['section']})"
            records["curriculum"].append({"id": i, "text": text, "metadata": clean({
                "kind": "lesson", "grades": [p["grade"]], "text": text, "source_url": p["url"],
                "license": p["license"], "attribution": p["attribution"]})})
    return records


def main() -> None:
    api_key, index_name, cloud, region = pinecone_settings()
    pc = Pinecone(api_key=api_key)
    if index_name not in [i.name for i in pc.list_indexes()]:
        pc.create_index(name=index_name, dimension=DIMENSIONS, metric="cosine",
                        spec=ServerlessSpec(cloud=cloud, region=region))
        while not pc.describe_index(index_name).status["ready"]:
            time.sleep(2)
    index = pc.Index(index_name)
    embedder = OpenAIEmbeddings(model=EMBED_MODEL, dimensions=DIMENSIONS)

    for namespace, rows in build_records().items():
        for start in range(0, len(rows), BATCH):
            chunk = rows[start:start + BATCH]
            vectors = embedder.embed_documents([r["text"] for r in chunk])
            index.upsert(vectors=[{"id": r["id"], "values": v, "metadata": r["metadata"]} for r, v in zip(chunk, vectors)],
                         namespace=namespace)
        print(f"{namespace:<11} {len(rows):>6,} vectors")

    time.sleep(5)
    stats = index.describe_index_stats()
    print({ns: s.vector_count for ns, s in stats.namespaces.items()}, "| dimension:", stats.dimension)


if __name__ == "__main__":
    main()
