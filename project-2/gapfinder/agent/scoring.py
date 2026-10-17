"""Plain-Python rules for scoring the check and choosing the gap. No AI in this file.

A skill is checked with 2 verified problems per round:
  all right -> solid, all wrong (or "didn't know") -> gap, a mix -> unclear.
Across two rounds (4 problems): 3+ right -> solid, 1 or fewer -> gap, 2 -> unclear.
"""
from gapfinder.answers import RELATIONS, AnswerError, parse_value

SOLID, GAP, UNCLEAR = "solid", "gap", "unclear"


def is_correct(kind: str, answer: str | None, key: str) -> bool:
    """None means the child didn't know, which counts as not correct."""
    if answer is None or not str(answer).strip():
        return False
    answer = str(answer).strip()
    if kind == "comparison":
        return answer in RELATIONS and answer == key
    try:
        return parse_value(answer) == parse_value(key)
    except AnswerError:
        return False


def verdict(right: int, total: int) -> str:
    if total == 0:
        return UNCLEAR
    share = right / total
    if share >= 0.75:
        return SOLID
    if share <= 0.25:
        return GAP
    return UNCLEAR


def verdicts(results: list[dict]) -> dict[str, str]:
    """results: [{"skill_code": ..., "correct": bool}, ...] across all rounds."""
    tally: dict[str, list[int]] = {}
    for r in results:
        right_total = tally.setdefault(r["skill_code"], [0, 0])
        right_total[0] += int(r["correct"])
        right_total[1] += 1
    return {code: verdict(right, total) for code, (right, total) in tally.items()}


def foundational_order(skills: list[dict]) -> list[dict]:
    """Most foundational first: furthest back in the Coherence Map, then lowest grade."""
    def grade_rank(s):
        grades = [g for g in s.get("grades", []) if g]
        g = min(grades, key=lambda x: (x != "K", x)) if grades else "9"
        return -1 if g in ("K", "KG") else int(g) if g.isdigit() else 99
    return sorted(skills, key=lambda s: (-s.get("hops", 0), grade_rank(s)))


def choose_gap(skills: list[dict], skill_verdicts: dict[str, str], round_number: int) -> dict:
    """Return {"code", "kind", "confidence"}.

    kind: "gap" (a skill the child missed), "unclear" (nothing definite), or "none" (every skill solid).
    """
    ordered = [s for s in foundational_order(skills) if s["code"] in skill_verdicts]
    gaps = [s for s in ordered if skill_verdicts[s["code"]] == GAP]
    unclear = [s for s in ordered if skill_verdicts[s["code"]] == UNCLEAR]
    if gaps:
        confidence = "high" if round_number == 1 and not unclear else "medium"
        return {"code": gaps[0]["code"], "kind": "gap", "confidence": confidence}
    if unclear:
        return {"code": unclear[0]["code"], "kind": "unclear", "confidence": "low"}
    target = next((s for s in skills if s.get("role") == "target"), skills[0])
    return {"code": target["code"], "kind": "none", "confidence": "high"}
