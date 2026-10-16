"""Load data/processed/graph/ into Neo4j (idempotent: MERGE on id).

Usage: uv run python -m gapfinder.graph.load [--wipe]
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from neo4j import GraphDatabase

from gapfinder.config import PROCESSED_GRAPH, neo4j_settings

BATCH = 2000
LABELS = {"Framework", "Standard", "SkillComponent", "Lesson", "Problem"}
SCHEMA = Path(__file__).with_name("schema.cypher")


def batches(rows: list, size: int = BATCH):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wipe", action="store_true", help="delete everything in the database first")
    args = parser.parse_args()

    nodes = defaultdict(list)
    for line in open(PROCESSED_GRAPH / "nodes.jsonl", encoding="utf-8"):
        n = json.loads(line)
        assert n["label"] in LABELS, n["label"]
        nodes[n["label"]].append({"id": n["id"], "props": {k: v for k, v in n["props"].items() if v is not None}})
    label_of = {r["id"]: label for label, rows in nodes.items() for r in rows}
    rels = defaultdict(list)
    for line in open(PROCESSED_GRAPH / "rels.jsonl", encoding="utf-8"):
        r = json.loads(line)
        key = (r["type"], label_of[r["from"]], label_of[r["to"]])
        rels[key].append({"from": r["from"], "to": r["to"], "props": {k: v for k, v in r["props"].items() if v is not None}})

    uri, auth = neo4j_settings()
    with GraphDatabase.driver(uri, auth=auth) as driver:
        if args.wipe:
            driver.execute_query("MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS")
        for statement in SCHEMA.read_text().split(";"):
            body = "\n".join(l for l in statement.splitlines() if not l.strip().startswith("//")).strip()
            if body:
                driver.execute_query(body)

        for label, rows in nodes.items():
            for chunk in batches(rows):
                driver.execute_query(f"UNWIND $rows AS r MERGE (n:{label} {{id: r.id}}) SET n += r.props", rows=chunk)
            print(f"nodes {label:<15} {len(rows):>7,}")
        for (rtype, a, b), rows in rels.items():
            for chunk in batches(rows):
                driver.execute_query(
                    f"UNWIND $rows AS r MATCH (s:{a} {{id: r.from}}) MATCH (t:{b} {{id: r.to}}) "
                    f"MERGE (s)-[x:{rtype}]->(t) SET x += r.props", rows=chunk)
            print(f"rels  {rtype:<15} {len(rows):>7,}  ({a} -> {b})")

        n = driver.execute_query("MATCH (n) RETURN count(n) AS c").records[0]["c"]
        m = driver.execute_query("MATCH ()-[r]->() RETURN count(r) AS c").records[0]["c"]
        print(f"\nDatabase now has {n:,} nodes ({n / 200_000:.0%} of 200k) and {m:,} relationships ({m / 400_000:.0%} of 400k)")


if __name__ == "__main__":
    main()
