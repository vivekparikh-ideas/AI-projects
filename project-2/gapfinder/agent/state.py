"""The agent's saved state, one record per browser session (thread).

Nothing here identifies the child: only the problem text, the skills, the check answers and the result.
Answer keys stay in this server-side state and are never sent to the screen.
"""
from typing import TypedDict


class GapState(TypedDict, total=False):
    # From the parent (wizard step 1)
    state_code: str | None          # jurisdiction name, e.g. "California"; None means Common Core
    grade: str                      # "K".."8"
    problem_text: str

    # Matching
    skill_description: str
    candidates: list[dict]          # [{code, text, score}]
    target_code: str
    target_text: str
    confidence: float
    state_wording: dict | None      # {code, text, jaccard} for display only

    # The check
    skills: list[dict]              # [{code, text, grades, hops, role: "target"|"prereq"}]
    pending_skills: list[str]       # skill codes to build checks for this round
    checks: list[dict]              # every check problem so far: {id, text, kind, answer_key, skill_code, round}
    round: int
    answers: dict[str, str | None]  # problem id -> answer; None means "didn't know"
    results: list[dict]             # [{problem_id, skill_code, correct}]
    verdicts: dict[str, str]        # skill code -> solid | gap | unclear

    # The result
    gap: dict                       # {code, kind, confidence}
    gap_text: str
    lessons: list[dict]
    result: dict                    # {headline, why, lesson_ids} or {abstained: True, ...}
    grade_feedback: str | None
    retry_count: int

    # Ask why
    chat: list[dict]                # [{question, answer, lesson_ids, grounded}]
