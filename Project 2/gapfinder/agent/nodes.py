"""The agent's steps. Each function takes the saved state and returns the fields it changes.

AI is used in describe_skill, match_standard (picking), generate_result and grade only.
Everything else is a graph lookup or plain Python (see the Gap Finder Agent Flow artifact).
"""
import re
from typing import Literal

from langgraph.types import interrupt
from pydantic import BaseModel, Field

from gapfinder.agent import scoring
from gapfinder.agent.resources import fast_model, neo4j, write_model
from gapfinder.agent.state import GapState
from gapfinder.config import CONFIDENCE_THRESHOLD, MAX_PREREQS, PROBLEMS_PER_SKILL
from gapfinder.graph import queries as Q
from gapfinder.vectors import retrieve

CCSS_CODE = re.compile(r"^(K|[1-8])\.[A-Z]+\.[A-Z]\.\d+")


def base_code(code: str) -> str:
    """Coherence Map links whole standards: '5.NF.B.7.c' -> '5.NF.B.7'."""
    m = CCSS_CODE.match(code or "")
    return m.group(0) if m else code


# ---------- matching ----------

class SkillDescription(BaseModel):
    is_math: bool = Field(description="True if this is a K-8 math problem or exercise.")
    description: str = Field(description="The skill the problem practices, in 6-15 plain words, plus the "
                                         "problem's numbers as an example. E.g. 'Divide a fraction by a fraction, e.g. 3/4 ÷ 1/8'.")


class StandardPick(BaseModel):
    code: str = Field(description="The code of the best-matching candidate, copied exactly.")
    confidence: float = Field(description="0 to 1: how sure you are this is the skill being practiced.")


def intake(state: GapState) -> dict:
    text = (state.get("problem_text") or "").strip()
    return {"problem_text": text[:1000], "round": 1, "retry_count": 0, "checks": [], "results": [],
            "answers": {}, "chat": [], "grade_feedback": None}


def describe_skill(state: GapState) -> dict:
    out = fast_model().with_structured_output(SkillDescription).invoke(
        f"A parent typed this grade {state['grade']} homework problem:\n{state['problem_text']}\n\n"
        "Describe the math skill it practices.")
    if not out.is_math:
        return {"skill_description": "", "result": {"not_math": True}}
    return {"skill_description": out.description}


def match_standard(state: GapState) -> dict:
    candidates = retrieve.match_standards(state["skill_description"], state["grade"], top_k=30, limit=8)
    for c in candidates:
        c["code"] = base_code(c["code"])
    texts = Q.standards(neo4j(), list({c["code"] for c in candidates}))
    seen, unique = set(), []
    for c in candidates:
        if c["code"] not in seen:
            seen.add(c["code"])
            info = texts.get(c["code"], {})
            unique.append({"code": c["code"], "text": info.get("text") or c["evidence"], "score": round(c["score"], 3)})
    listing = "\n".join(f"- {c['code']}: {c['text']}" for c in unique)
    pick = fast_model().with_structured_output(StandardPick).invoke(
        f"Grade {state['grade']} homework problem:\n{state['problem_text']}\n"
        f"Skill: {state['skill_description']}\n\nWhich Common Core standard is this problem practicing?\n{listing}")
    chosen = next((c for c in unique if c["code"] == pick.code), None)
    confidence = pick.confidence if chosen else 0.0
    if chosen:  # put the pick first so the confirm screen shows it as option 1
        unique = [chosen] + [c for c in unique if c is not chosen]
    return {"candidates": unique, "target_code": unique[0]["code"] if unique else None,
            "target_text": unique[0]["text"] if unique else None, "confidence": round(confidence, 2)}


def confirm_skill(state: GapState) -> dict:
    """Pause: the parent chooses between the top two skills."""
    choices = [{"code": c["code"], "text": c["text"]} for c in state["candidates"][:2]]
    chosen = interrupt({"type": "confirm_skill", "choices": choices})
    pick = next((c for c in choices if c["code"] == chosen), choices[0])
    return {"target_code": pick["code"], "target_text": pick["text"], "confidence": 1.0}


# ---------- the check ----------

def state_wording(state: GapState) -> dict:
    if not state.get("state_code"):
        return {"state_wording": None}
    return {"state_wording": Q.state_wording(neo4j(), state["state_code"], state["target_code"])}


def prereq_walk(state: GapState) -> dict:
    driver = neo4j()
    target = Q.standard(driver, state["target_code"]) or {"code": state["target_code"], "text": state.get("target_text"), "grades": []}
    skills = [{**target, "hops": 0, "role": "target"}]
    prereqs = [p for p in Q.prerequisites(driver, state["target_code"], limit=10) if p["problems"] >= PROBLEMS_PER_SKILL]
    skills += [{"code": p["code"], "text": p["text"], "grades": p["grades"], "hops": p["hops"], "role": "prereq"}
               for p in prereqs[:MAX_PREREQS]]
    return {"skills": skills, "pending_skills": [s["code"] for s in skills]}


def build_checks(state: GapState) -> dict:
    used = [c["id"] for c in state.get("checks", [])]
    new = []
    for code in state.get("pending_skills", []):
        for p in Q.check_problems(neo4j(), code, limit=PROBLEMS_PER_SKILL, exclude=used + [c["id"] for c in new]):
            new.append({"id": p["id"], "text": p["text"], "kind": p["kind"], "answer_key": p["answer_key"],
                        "skill_code": code, "round": state["round"], "source_url": p["source_url"]})
    return {"checks": state.get("checks", []) + new, "pending_skills": []}


def await_answers(state: GapState) -> dict:
    """Pause: the parent runs this round's check. Answer keys are not sent."""
    this_round = [c for c in state["checks"] if c["round"] == state["round"]]
    answers = interrupt({"type": "check", "round": state["round"],
                         "problems": [{"id": c["id"], "text": c["text"], "kind": c["kind"]} for c in this_round]})
    return {"answers": {**state.get("answers", {}), **(answers or {})}}


def score_answers(state: GapState) -> dict:
    scored = {r["problem_id"] for r in state.get("results", [])}
    new = [{"problem_id": c["id"], "skill_code": c["skill_code"],
            "correct": scoring.is_correct(c["kind"], state["answers"].get(c["id"]), c["answer_key"])}
           for c in state["checks"] if c["id"] not in scored]
    results = state.get("results", []) + new
    return {"results": results, "verdicts": scoring.verdicts(results)}


def narrow(state: GapState) -> dict:
    """Round 2: re-check unclear skills, and look one step further back below a missed skill."""
    v = state["verdicts"]
    known = {s["code"] for s in state["skills"]}
    pending = [code for code, verdict in v.items() if verdict == scoring.UNCLEAR]
    added = []
    for s in scoring.foundational_order([s for s in state["skills"] if v.get(s["code"]) == scoring.GAP])[:1]:
        for p in Q.prerequisites(neo4j(), s["code"], limit=5):
            if p["hops"] == 1 and p["code"] not in known and p["problems"] >= PROBLEMS_PER_SKILL:
                added.append({"code": p["code"], "text": p["text"], "grades": p["grades"],
                              "hops": s.get("hops", 0) + 1, "role": "prereq"})
                break
    pending += [a["code"] for a in added]
    return {"skills": state["skills"] + added, "pending_skills": pending[:MAX_PREREQS],
            "round": state["round"] + (1 if pending else 0)}


# ---------- the result ----------

class ResultText(BaseModel):
    headline: str = Field(description="One short sentence naming the likely gap in parent-friendly words.")
    why: str = Field(description="One or two sentences explaining what the check showed, using only the facts given.")
    lesson_ids: list[str] = Field(description="Ids of the lessons to recommend, copied exactly from the list, best first.")


class Grade(BaseModel):
    grounded: bool = Field(description="True only if every claim in the text is supported by the facts.")
    unsupported: list[str] = Field(default_factory=list, description="Claims not supported by the facts.")


def decide_gap(state: GapState) -> dict:
    gap = scoring.choose_gap(state["skills"], state["verdicts"], state["round"])
    skill = next((s for s in state["skills"] if s["code"] == gap["code"]), {})
    return {"gap": gap, "gap_text": skill.get("text") or ""}


def retrieve_lessons(state: GapState) -> dict:
    driver = neo4j()
    found = Q.lessons(driver, state["gap"]["code"], limit=8)
    if not found and state["gap"]["code"] != state["target_code"]:
        found = Q.lessons(driver, state["target_code"], limit=8)
    order = retrieve.rank_by_similarity([l["id"] for l in found], f"{state['skill_description']}. {state['gap_text']}")
    by_id = {l["id"]: l for l in found}
    return {"lessons": [by_id[i] for i, _ in order[:3]]}


def _facts(state: GapState) -> str:
    v = state["verdicts"]
    lines = [f"Homework problem (grade {state['grade']}): {state['problem_text']}",
             f"Homework skill {state['target_code']}: {state.get('target_text') or ''}"]
    for s in state["skills"]:
        right = sum(r["correct"] for r in state["results"] if r["skill_code"] == s["code"])
        total = sum(1 for r in state["results"] if r["skill_code"] == s["code"])
        if total:
            lines.append(f"Skill {s['code']} ({'homework skill' if s['role'] == 'target' else 'earlier skill'}): "
                         f"{s['text']} -> {right} of {total} right ({v.get(s['code'])})")
    gap = state["gap"]
    lines.append({"gap": f"Likely gap: {gap['code']} ({gap['confidence']} confidence).",
                  "unclear": f"No clear gap; least certain skill: {gap['code']} (low confidence).",
                  "none": "Every earlier skill checked was solid; no earlier gap found."}[gap["kind"]])
    lines += [f"Lesson {l['id']}: grade {l['grade']}, unit {l['unit']}, lesson {l['lesson']} - {l['title']}" for l in state["lessons"]]
    return "\n".join(lines)


def generate_result(state: GapState) -> dict:
    feedback = state.get("grade_feedback")
    prompt = ("Write the result for a parent. Use only these facts; do not add numbers, skills or lessons that are not listed. "
              "Write for a parent, not a teacher. Do not use standard codes in the headline.\n\n" + _facts(state))
    if feedback:
        prompt += f"\n\nA previous draft made unsupported claims: {feedback}. Remove them and stay strictly within the facts."
    out = write_model().with_structured_output(ResultText).invoke(prompt)
    return {"result": out.model_dump(), "retry_count": state.get("retry_count", 0) + (1 if feedback else 0)}


def grade(state: GapState) -> dict:
    result = state["result"]
    allowed = {l["id"] for l in state["lessons"]}
    bad_ids = [i for i in result.get("lesson_ids", []) if i not in allowed]
    bad_ids += Q.missing_ids(neo4j(), [i for i in result.get("lesson_ids", []) if i in allowed])
    if bad_ids:
        return {"grade_feedback": f"named lessons that are not in the list: {bad_ids}"}
    verdict = fast_model().with_structured_output(Grade).invoke(
        f"Facts:\n{_facts(state)}\n\nText to check:\nHeadline: {result['headline']}\nWhy: {result['why']}\n\n"
        "Is every claim in the text supported by the facts? Paraphrase is fine; new facts are not.")
    return {"grade_feedback": None if verdict.grounded else "; ".join(verdict.unsupported) or "unsupported claims"}


def cannot_check(state: GapState) -> dict:
    """No verified check problems for this skill or its earlier skills yet."""
    found = Q.lessons(neo4j(), state["target_code"], limit=3)
    return {"lessons": found, "result": {"cannot_check": True, "lesson_ids": [l["id"] for l in found]}}


def abstain(state: GapState) -> dict:
    return {"result": {"abstained": True, "headline": "We couldn't pinpoint one skill.",
                       "why": "The check didn't give a clear enough answer. These lessons cover the skills we looked at.",
                       "lesson_ids": [l["id"] for l in state.get("lessons", [])]}}


# ---------- routing (plain Python) ----------

def route_after_describe(state: GapState) -> Literal["match_standard", "__end__"]:
    return "__end__" if state.get("result", {}).get("not_math") else "match_standard"


def route_after_match(state: GapState) -> Literal["state_wording", "confirm_skill"]:
    confident = state.get("confidence", 0) >= CONFIDENCE_THRESHOLD and state.get("target_code")
    return "state_wording" if confident else "confirm_skill"


def route_after_checks(state: GapState) -> Literal["await_answers", "decide_gap", "cannot_check"]:
    has_new = any(c["round"] == state["round"] for c in state.get("checks", []))
    if has_new:
        return "await_answers"
    # Nothing to check at all: say so instead of reporting "no earlier gap" (decisions.md #19).
    return "cannot_check" if not state.get("checks") else "decide_gap"


def route_after_score(state: GapState) -> Literal["narrow", "decide_gap"]:
    from gapfinder.config import MAX_ROUNDS
    needs_more = any(v in (scoring.UNCLEAR, scoring.GAP) for v in state["verdicts"].values())
    return "narrow" if state["round"] < MAX_ROUNDS and needs_more else "decide_gap"


def route_after_narrow(state: GapState) -> Literal["build_checks", "decide_gap"]:
    return "build_checks" if state.get("pending_skills") else "decide_gap"


def route_after_grade(state: GapState) -> Literal["__end__", "generate_result", "abstain"]:
    if not state.get("grade_feedback"):
        return "__end__"
    return "generate_result" if state.get("retry_count", 0) < 1 else "abstain"
