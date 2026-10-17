"""Routing decisions are plain Python, so they're tested without any model or database."""
from gapfinder.agent import nodes as n


def test_not_math_ends_early():
    assert n.route_after_describe({"result": {"not_math": True}}) == "__end__"
    assert n.route_after_describe({"skill_description": "Add fractions"}) == "match_standard"


def test_low_confidence_asks_the_parent():
    assert n.route_after_match({"confidence": 0.95, "target_code": "6.NS.A.1"}) == "state_wording"
    assert n.route_after_match({"confidence": 0.4, "target_code": "6.NS.A.1"}) == "confirm_skill"
    assert n.route_after_match({"confidence": 0.9, "target_code": None}) == "confirm_skill"


def test_no_problems_skips_the_check():
    assert n.route_after_checks({"round": 1, "checks": [{"round": 1}]}) == "await_answers"
    assert n.route_after_checks({"round": 2, "checks": [{"round": 1}]}) == "decide_gap"


def test_nothing_to_check_says_so():
    assert n.route_after_checks({"round": 1, "checks": []}) == "cannot_check"


def test_round_two_only_when_needed_and_allowed():
    assert n.route_after_score({"round": 1, "verdicts": {"a": "unclear"}}) == "narrow"
    assert n.route_after_score({"round": 1, "verdicts": {"a": "solid"}}) == "decide_gap"
    assert n.route_after_score({"round": 2, "verdicts": {"a": "unclear"}}) == "decide_gap"


def test_narrow_with_nothing_new_goes_to_decision():
    assert n.route_after_narrow({"pending_skills": ["5.NF.B.7"]}) == "build_checks"
    assert n.route_after_narrow({"pending_skills": []}) == "decide_gap"


def test_one_rewrite_then_abstain():
    assert n.route_after_grade({"grade_feedback": None}) == "__end__"
    assert n.route_after_grade({"grade_feedback": "x", "retry_count": 0}) == "generate_result"
    assert n.route_after_grade({"grade_feedback": "x", "retry_count": 1}) == "abstain"


def test_base_code():
    assert n.base_code("5.NF.B.7.c") == "5.NF.B.7"
    assert n.base_code("6.NS.A.1") == "6.NS.A.1"
    assert n.base_code("K.CC.A.1") == "K.CC.A.1"
