from gapfinder.agent.scoring import GAP, SOLID, UNCLEAR, choose_gap, is_correct, verdicts

SKILLS = [
    {"code": "6.NS.A.1", "grades": ["6"], "hops": 0, "role": "target"},
    {"code": "5.NF.B.7", "grades": ["5"], "hops": 1, "role": "prereq"},
    {"code": "4.NF.B.4", "grades": ["4"], "hops": 2, "role": "prereq"},
]


def results(**right_by_skill):
    out = []
    for code, rights in right_by_skill.items():
        for ok in rights:
            out.append({"skill_code": code.replace("_", "."), "correct": ok})
    return out


def test_is_correct():
    assert is_correct("value", "3/6", "1/2")
    assert is_correct("value", "0.5", "1/2")
    assert is_correct("value", "1 1/2", "3/2")
    assert not is_correct("value", None, "1/2")
    assert not is_correct("value", "half", "1/2")
    assert is_correct("comparison", ">", ">")
    assert not is_correct("comparison", "<", ">")


def test_verdicts_per_round_and_across_rounds():
    v = verdicts(results(**{"6_NS_A_1": [False, False], "5_NF_B_7": [True, False], "4_NF_B_4": [True, True]}))
    assert v == {"6.NS.A.1": GAP, "5.NF.B.7": UNCLEAR, "4.NF.B.4": SOLID}
    assert verdicts(results(**{"5_NF_B_7": [True, False, True, True]})) == {"5.NF.B.7": SOLID}
    assert verdicts(results(**{"5_NF_B_7": [True, False, False, False]})) == {"5.NF.B.7": GAP}


def test_choose_most_foundational_gap():
    v = {"6.NS.A.1": GAP, "5.NF.B.7": GAP, "4.NF.B.4": SOLID}
    assert choose_gap(SKILLS, v, 1) == {"code": "5.NF.B.7", "kind": "gap", "confidence": "high"}


def test_gap_with_unclear_or_round_two_is_medium():
    v = {"6.NS.A.1": GAP, "5.NF.B.7": UNCLEAR, "4.NF.B.4": SOLID}
    assert choose_gap(SKILLS, v, 1)["confidence"] == "medium"
    assert choose_gap(SKILLS, {"6.NS.A.1": GAP}, 2)["confidence"] == "medium"


def test_only_unclear_is_low():
    v = {"6.NS.A.1": UNCLEAR, "5.NF.B.7": UNCLEAR, "4.NF.B.4": SOLID}
    assert choose_gap(SKILLS, v, 2) == {"code": "5.NF.B.7", "kind": "unclear", "confidence": "low"}


def test_all_solid_points_to_target():
    v = {"6.NS.A.1": SOLID, "5.NF.B.7": SOLID, "4.NF.B.4": SOLID}
    assert choose_gap(SKILLS, v, 1) == {"code": "6.NS.A.1", "kind": "none", "confidence": "high"}
