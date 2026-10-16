"""Run one agent request while showing the waiting screen with live progress (decisions.md #19)."""
import streamlit as st

from gapfinder.agent.graph import agent
from ui.components import checklist, esc, show, tilly

FIND = [("describe_skill", "Understanding the problem"), ("match_standard", "Matching to Common Core"),
        ("prereq_walk", "Looking up earlier skills"), ("build_checks", "Picking check questions")]
CONFIRMED = [("prereq_walk", "Looking up earlier skills"), ("build_checks", "Picking check questions")]
ANSWERS = [("score_answers", "Scoring the answers"), ("decide_gap", "Finding the gap"), ("retrieve_lessons", "Choosing lessons"),
           ("generate_result", "Writing the result"), ("grade", "Checking it against sources")]
EXTRA = {"narrow": "Picking 2 more questions to be sure", "build_checks": "Picking check questions",
         "cannot_check": "Checking what we can test", "abstain": "Wrapping up"}


def run(graph_input, thread_id: str, steps: list[tuple[str, str]], title: str = "Finding the gap…"):
    """Stream the agent and tick off steps as they finish. Returns (pause payload or None, final state values)."""
    show(f'<div style="display:flex;flex-direction:column;align-items:center;gap:14px;margin:30px 0 18px">{tilly(88, "curious", -6)}'
         f'<div class="gf-h1" style="text-align:center">{esc(title)}</div>'
         '<p class="gf-muted" style="margin:0">This takes about 3 seconds.</p></div>')
    box = st.empty()
    items, done, details = list(steps), set(), {}
    box.markdown(checklist(items, done, items[0][0], details), unsafe_allow_html=True)

    config = {"configurable": {"thread_id": thread_id}}
    for update in agent().stream(graph_input, config, stream_mode="updates"):
        node = next(iter(update))
        if node == "__interrupt__":
            continue
        if node not in {k for k, _ in items} and node in EXTRA:
            items.append((node, EXTRA[node]))
        if node == "match_standard" and (update[node] or {}).get("target_code"):
            details[node] = update[node]["target_code"]
        done.add(node)
        current = next((k for k, _ in items if k not in done), None)
        box.markdown(checklist(items, done, current, details), unsafe_allow_html=True)

    snapshot = agent().get_state(config)
    pause = next((i.value for task in snapshot.tasks for i in task.interrupts), None)
    return pause, snapshot.values
