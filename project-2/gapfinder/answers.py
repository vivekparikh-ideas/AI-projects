"""Deterministic answer checking for numbers, fractions, decimals and comparisons.

Answers are parsed with a small whitelisted arithmetic evaluator over exact Fractions.
Model output and user input are never passed to eval().
"""
import ast
import operator
import re
from fractions import Fraction

_ALLOWED = re.compile(r"^[0-9+\-*/(). ]+$")
_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_MIXED = re.compile(r"(?<![\d/.])(\d+)\s+(\d+)\s*/\s*(\d+)")
_DIV_FRACTION = re.compile(r"÷\s*(\d+)\s*/\s*(\d+)")
RELATIONS = ("<", ">", "=")


class AnswerError(ValueError):
    """The text is not a number, fraction, decimal or arithmetic expression we accept."""


def _eval(node: ast.AST) -> Fraction:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return Fraction(str(node.value))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Div) and right == 0:
            raise AnswerError("division by zero")
        return _BINARY[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    raise AnswerError(f"unsupported syntax: {type(node).__name__}")


def parse_value(text: str) -> Fraction:
    """Parse '3/4', '0.75', '1 1/2', '2 + 1/3' or '(1/2) / (1/8)' into an exact Fraction."""
    s = (text or "").strip().replace("−", "-").replace("×", "*").replace(",", "")
    s = _MIXED.sub(lambda m: f"({m.group(1)}+{m.group(2)}/{m.group(3)})", s)
    # "12 ÷ 3/4" means 12 ÷ (3/4): a fraction after ÷ is one number.
    s = _DIV_FRACTION.sub(r"/(\1/\2)", s).replace("÷", "/")
    if not s or not _ALLOWED.match(s) or len(s) > 200:
        raise AnswerError(f"not a number or arithmetic expression: {text!r}")
    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError as exc:
        raise AnswerError(f"cannot parse {text!r}") from exc
    return _eval(tree)


def compare(left: str, right: str) -> str:
    """Return '<', '>' or '=' for two values."""
    a, b = parse_value(left), parse_value(right)
    return "<" if a < b else ">" if a > b else "="


def same_value(a: str, b: str) -> bool:
    """True when two answers are numerically equal (3/6 == 1/2 == 0.5)."""
    try:
        return parse_value(a) == parse_value(b)
    except AnswerError:
        return False


def describe(value: Fraction) -> dict:
    """Canonical forms of a value, for display and storage."""
    out = {"fraction": f"{value.numerator}/{value.denominator}" if value.denominator != 1 else str(value.numerator)}
    whole, rest = divmod(abs(value.numerator), value.denominator)
    if whole and rest:
        out["mixed"] = f"{'-' if value < 0 else ''}{whole} {rest}/{value.denominator}"
    d = value.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    if d == 1:
        out["decimal"] = format(value.numerator / value.denominator, "g")
    return out
