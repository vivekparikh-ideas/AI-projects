from fractions import Fraction

import pytest

from gapfinder.answers import AnswerError, compare, describe, parse_value, same_value


@pytest.mark.parametrize("text, expected", [
    ("3/4", Fraction(3, 4)),
    ("0.75", Fraction(3, 4)),
    ("1 1/2", Fraction(3, 2)),
    ("2 + 1/3", Fraction(7, 3)),
    ("(1/2) / (1/8)", Fraction(4)),
    ("12 ÷ 3/4", Fraction(16)),
    ("−2/3", Fraction(-2, 3)),
    ("1,000", Fraction(1000)),
])
def test_parse_value(text, expected):
    assert parse_value(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "__import__('os')", "2**1000", "1/0", "x + 1"])
def test_parse_value_rejects(text):
    with pytest.raises(AnswerError):
        parse_value(text)


def test_same_value_equivalent_forms():
    assert same_value("3/6", "1/2")
    assert same_value("0.5", "1/2")
    assert not same_value("1/3", "0.33")
    assert not same_value("pizza", "1/2")


def test_compare():
    assert compare("1/8", "1/10") == ">"
    assert compare("4/10", "7/10") == "<"
    assert compare("2/4", "0.5") == "="


def test_describe():
    assert describe(Fraction(3, 2)) == {"fraction": "3/2", "mixed": "1 1/2", "decimal": "1.5"}
    assert describe(Fraction(1, 3)) == {"fraction": "1/3"}
    assert describe(Fraction(4)) == {"fraction": "4", "decimal": "4"}
