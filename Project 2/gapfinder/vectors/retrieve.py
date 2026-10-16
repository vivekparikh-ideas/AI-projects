"""Vector lookups against Pinecone."""
from collections import defaultdict
from functools import lru_cache

from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone

from gapfinder.config import pinecone_settings
from gapfinder.vectors.index import DIMENSIONS, EMBED_MODEL

GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8"]


@lru_cache(maxsize=1)
def _clients():
    api_key, index_name, _, _ = pinecone_settings()
    return Pinecone(api_key=api_key).Index(index_name), OpenAIEmbeddings(model=EMBED_MODEL, dimensions=DIMENSIONS)


def grade_window(grade: str, back: int = 1) -> list[str]:
    """The child's grade and the grades just before it, e.g. '6' -> ['5', '6']."""
    i = GRADE_ORDER.index(grade)
    return GRADE_ORDER[max(0, i - back): i + 1]


def rank_by_similarity(ids: list[str], text: str, namespace: str = "curriculum") -> list[tuple[str, float]]:
    """Order a short list of known ids (chosen by the graph) by similarity to a text."""
    if not ids:
        return []
    index, embedder = _clients()
    query = embedder.embed_query(text)
    vectors = index.fetch(ids=ids, namespace=namespace).vectors
    scored = []
    for i in ids:
        if i in vectors:
            v = vectors[i].values
            scored.append((i, sum(a * b for a, b in zip(query, v))))  # OpenAI embeddings are unit length
        else:
            scored.append((i, 0.0))
    return sorted(scored, key=lambda kv: kv[1], reverse=True)


def search(text: str, namespace: str = "curriculum", top_k: int = 4, kinds: list[str] | None = None) -> list[dict]:
    """Plain similarity search, returning id, score and metadata."""
    index, embedder = _clients()
    flt = {"kind": {"$in": kinds}} if kinds else None
    result = index.query(namespace=namespace, vector=embedder.embed_query(text), top_k=top_k,
                         include_metadata=True, filter=flt)
    return [{"id": m.id, "score": m.score, **m.metadata} for m in result.matches]


def match_standards(problem_text: str, grade: str, top_k: int = 15, limit: int = 3) -> list[dict]:
    """Common Core standards that best match a homework problem, best first.

    Searches standards and skill components within the child's grade window, then scores each
    standard by its best-matching item.
    """
    index, embedder = _clients()
    result = index.query(namespace="standards", vector=embedder.embed_query(problem_text), top_k=top_k,
                         include_metadata=True, filter={"grades": {"$in": grade_window(grade)}})
    best = defaultdict(lambda: {"score": 0.0, "evidence": None})
    for m in result.matches:
        for code in m.metadata.get("codes", []):
            if m.score > best[code]["score"]:
                best[code] = {"score": m.score, "evidence": m.metadata.get("text"), "kind": m.metadata.get("kind"),
                              "grades": m.metadata.get("grades", [])}
    ranked = sorted(best.items(), key=lambda kv: kv[1]["score"], reverse=True)[:limit]
    return [{"code": code, **info} for code, info in ranked]
