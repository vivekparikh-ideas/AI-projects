"""The "Ask why" chat on the result screen.

Reads the finished session from the checkpointer, adds Pinecone and Neo4j context, answers from that
context only, runs the same grounding check, and appends the turn to the session's chat.
"""
from pydantic import BaseModel, Field

from gapfinder.agent.graph import agent
from gapfinder.agent.nodes import Grade, _facts
from gapfinder.agent.resources import fast_model, neo4j, write_model
from gapfinder.config import MAX_CHAT_TURNS
from gapfinder.graph import queries as Q
from gapfinder.vectors import retrieve

NO_SOURCE = "I don't have a source for that. The lessons above are the best place to start."


class ChatAnswer(BaseModel):
    answer: str = Field(description="A short, plain answer for a parent (2-5 sentences), using only the context.")
    lesson_ids: list[str] = Field(default_factory=list, description="Ids of lessons from the context that the answer relies on.")


def ask_why(thread_id: str, question: str) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    state = agent().get_state(config).values
    chat = state.get("chat", [])
    if not state.get("result"):
        raise ValueError("This session has no result yet.")
    if len(chat) >= MAX_CHAT_TURNS:
        return {"question": question, "answer": "That's the limit for this session. Start over to check another problem.",
                "lesson_ids": [], "grounded": True, "limit_reached": True}

    gap_code = state["gap"]["code"]
    hits = retrieve.search(question + " " + state.get("gap_text", ""), namespace="curriculum", top_k=4)
    before = Q.prerequisites(neo4j(), gap_code, limit=3)
    after = Q.next_skills(neo4j(), gap_code)
    context = "\n".join([
        _facts(state),
        *[f"Related {h['kind']} {h['id']}: {h.get('text', '')}" for h in hits],
        *[f"Comes before {gap_code}: {p['code']} {p['text']}" for p in before],
        *[f"{gap_code} leads to: {n['code']} {n['text']}" for n in after],
    ])
    out = write_model().with_structured_output(ChatAnswer).invoke(
        f"Context:\n{context}\n\nA parent asks: {question}\n\n"
        "Answer only from the context. Do not invent new practice problems or numbers. "
        "If the context doesn't answer the question, say so.")
    verdict = fast_model().with_structured_output(Grade).invoke(
        f"Facts:\n{context}\n\nText to check:\n{out.answer}\n\nIs every claim in the text supported by the facts?")
    # Cited lessons must come from the context and exist in the graph.
    allowed = {l["id"] for l in state.get("lessons", [])} | {h["id"] for h in hits if h.get("kind") == "lesson"}
    cited = [i for i in out.lesson_ids if i in allowed]
    missing = set(Q.missing_ids(neo4j(), cited)) if cited else set()
    cited = [i for i in cited if i not in missing]
    turn = {"question": question, "answer": out.answer if verdict.grounded else NO_SOURCE,
            "lesson_ids": cited if verdict.grounded else [], "grounded": verdict.grounded}
    agent().update_state(config, {"chat": chat + [turn]})
    return turn
