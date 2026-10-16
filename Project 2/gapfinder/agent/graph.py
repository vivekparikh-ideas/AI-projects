"""Wire the nodes into a LangGraph state machine with a SQLite checkpointer.

The graph pauses at confirm_skill and await_answers (LangGraph interrupts). The screen resumes it with
Command(resume=...). Progress is saved per thread_id (one per browser session) in data/sessions.sqlite.
"""
import sqlite3
from functools import lru_cache

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from gapfinder.agent import nodes as n
from gapfinder.agent.state import GapState
from gapfinder.config import SESSIONS_DB


def build(checkpointer=None):
    g = StateGraph(GapState)
    for name in ("intake", "describe_skill", "match_standard", "confirm_skill", "state_wording", "prereq_walk",
                 "build_checks", "await_answers", "score_answers", "narrow", "decide_gap", "retrieve_lessons",
                 "generate_result", "grade", "abstain", "cannot_check"):
        g.add_node(name, getattr(n, name))

    g.add_edge(START, "intake")
    g.add_edge("intake", "describe_skill")
    g.add_conditional_edges("describe_skill", n.route_after_describe, {"match_standard": "match_standard", "__end__": END})
    g.add_conditional_edges("match_standard", n.route_after_match)
    g.add_edge("confirm_skill", "state_wording")
    g.add_edge("state_wording", "prereq_walk")
    g.add_edge("prereq_walk", "build_checks")
    g.add_conditional_edges("build_checks", n.route_after_checks)
    g.add_edge("await_answers", "score_answers")
    g.add_conditional_edges("score_answers", n.route_after_score)
    g.add_conditional_edges("narrow", n.route_after_narrow)
    g.add_edge("decide_gap", "retrieve_lessons")
    g.add_edge("retrieve_lessons", "generate_result")
    g.add_edge("generate_result", "grade")
    g.add_conditional_edges("grade", n.route_after_grade, {"__end__": END, "generate_result": "generate_result", "abstain": "abstain"})
    g.add_edge("abstain", END)
    g.add_edge("cannot_check", END)
    return g.compile(checkpointer=checkpointer)


@lru_cache(maxsize=1)
def agent():
    """The compiled agent with progress saved to data/sessions.sqlite."""
    SESSIONS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SESSIONS_DB, check_same_thread=False)
    return build(SqliteSaver(conn))
