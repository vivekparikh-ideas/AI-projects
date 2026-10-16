"""Derive answer keys for the pilot problems (decisions.md #16).

For each problem in data/interim/im_first_edition_pilot/problems.jsonl:
  1. EXTRACT (model A): split the problem into self-contained parts. For each part, decide whether it
     has a single checkable answer (a number/fraction/decimal or a <, >, = comparison) and write the
     arithmetic for it. The model writes arithmetic only; it does not give the answer.
  2. COMPUTE: evaluate that arithmetic exactly with gapfinder.answers (no eval of model output).
  3. SOLVE (model B, a different model): solve the same part independently, without seeing step 1.
  4. COMPARE: 'agreed' when compute and solve match, otherwise 'disagree' (always sent to review).

Model responses are cached under llm_cache/ so re-runs cost nothing.
Writes answer_keys.jsonl (one record per part) and answer_keys_summary.json.

Usage: uv run python scripts/derive_answer_keys.py [--limit N]
"""
import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gapfinder.answers import AnswerError, compare, describe, parse_value  # noqa: E402

EXTRACT_MODEL = "gpt-5.5"
SOLVE_MODEL = "o4-mini"
PILOT_DIR = ROOT / "data" / "interim" / "im_first_edition_pilot"
CACHE = PILOT_DIR / "llm_cache"


class Part(BaseModel):
    label: str = Field(description="Part label as written in the problem (a, b, 1, ...), or '1' if there is only one part.")
    text: str = Field(description="The part rewritten as a self-contained question, including any numbers it needs from the problem stem.")
    kind: Literal["value", "comparison", "not_checkable"] = Field(
        description="value: the answer is one number, fraction or decimal. comparison: the answer is <, > or = between two given numbers. "
                    "not_checkable: anything else (explanations, drawings, several answers, choosing from a picture, open-ended).")
    needs_image: bool = Field(description="True if the part cannot be answered from the text and image descriptions alone.")
    expression: str | None = Field(
        default=None,
        description="For kind=value only: plain arithmetic whose result is the answer, using digits, + - * / and parentheses. "
                    "Write mixed numbers as (1+1/2). No words, variables or functions.")
    left: str | None = Field(default=None, description="For kind=comparison only: the first number, as arithmetic.")
    right: str | None = Field(default=None, description="For kind=comparison only: the second number, as arithmetic.")
    standard: str | None = Field(default=None, description="The single best-matching code from the candidate standards list.")
    note: str | None = Field(default=None, description="For not_checkable parts: a few words on why.")


class Extraction(BaseModel):
    parts: list[Part]


class Solution(BaseModel):
    kind: Literal["value", "comparison"]
    answer: str = Field(description="For value: the final number, fraction or decimal only (e.g. 3/4, 1 1/2, 0.6). For comparison: exactly one of <, >, =.")


EXTRACT_PROMPT = """You prepare a K-8 math practice problem for automatic answer checking.
Split it into its parts. For each part decide if it has exactly one checkable answer.
Do NOT state answers. For value parts, write the arithmetic that produces the answer; for comparisons, write the two numbers.
If a part asks the student to explain, draw, describe, agree or disagree, or has more than one answer, it is not_checkable
(a part that asks for a number AND an explanation is still 'value' if the number alone can be checked).
Pick the single best standard for each part from this list: {standards}

Problem (LaTeX math between \\( and \\)):
{text}

Image descriptions:
{images}"""

SOLVE_PROMPT = """Solve this K-8 math question. Reply with the final answer only, in the required format.
Background from the full problem:
{context}

Question:
{question}"""


def cached(kind: str, key: str, call):
    path = CACHE / kind / f"{key.replace(':', '_').replace('/', '_')}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    result = call().model_dump()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def process(problem: dict, extractor, solver) -> list[dict]:
    images = "\n".join(f"- {i['alt']} {i['description']}".strip() for i in problem["images"]) or "(none)"
    extraction = cached("extract", problem["id"], lambda: extractor.invoke(EXTRACT_PROMPT.format(
        standards=", ".join(problem["standards"]), text=problem["text"], images=images)))

    records = []
    for n, part in enumerate(extraction["parts"], start=1):
        rec = {
            "part_id": f"{problem['id']}#{n}",
            "problem_id": problem["id"],
            "label": part["label"],
            "part_text": part["text"],
            "kind": part["kind"],
            "needs_image": part["needs_image"],
            "standard": part["standard"],
            "candidate_standards": problem["standards"],
            "grade": problem["grade"],
            "source_url": problem["source_url"],
            "computed": None, "solver_answer": None, "answer_key": None,
            "status": "not_checkable", "note": part["note"],
            "method": {"extract_model": EXTRACT_MODEL, "solve_model": SOLVE_MODEL, "compute": "gapfinder.answers (exact fractions)"},
            "expression": part["expression"], "left": part["left"], "right": part["right"],
        }
        if part["kind"] == "not_checkable" or part["needs_image"]:
            records.append(rec)
            continue
        try:
            if part["kind"] == "value":
                value = parse_value(part["expression"])
                rec["computed"] = describe(value)["fraction"]
            else:
                rec["computed"] = compare(part["left"], part["right"])
        except (AnswerError, TypeError) as exc:
            rec.update(status="compute_error", note=str(exc))
            records.append(rec)
            continue

        solution = cached("solve", rec["part_id"], lambda: solver.invoke(SOLVE_PROMPT.format(
            context=problem["text"], question=part["text"])))
        rec["solver_answer"] = solution["answer"].strip()
        if part["kind"] == "value":
            try:
                agree = solution["kind"] == "value" and parse_value(rec["solver_answer"]) == parse_value(rec["computed"])
            except AnswerError:
                agree = False
        else:
            agree = rec["solver_answer"] == rec["computed"]
        rec["status"] = "agreed" if agree else "disagree"
        rec["answer_key"] = rec["computed"] if agree else None
        records.append(rec)
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="only process the first N problems")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    extractor = ChatOpenAI(model=EXTRACT_MODEL).with_structured_output(Extraction)
    solver = ChatOpenAI(model=SOLVE_MODEL).with_structured_output(Solution)
    problems = [json.loads(line) for line in open(PILOT_DIR / "problems.jsonl", encoding="utf-8")][: args.limit]

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda p: process(p, extractor, solver), problems))
    parts = [r for rs in results for r in rs]

    with open(PILOT_DIR / "answer_keys.jsonl", "w", encoding="utf-8") as f:
        for r in parts:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {
        "problems": len(problems),
        "parts": len(parts),
        "by_status": dict(Counter(r["status"] for r in parts)),
        "checkable_problems": len({r["problem_id"] for r in parts if r["status"] in ("agreed", "disagree", "compute_error")}),
        "agreed_by_grade": dict(sorted(Counter(r["grade"] for r in parts if r["status"] == "agreed").items())),
        "models": {"extract": EXTRACT_MODEL, "solve": SOLVE_MODEL},
    }
    (PILOT_DIR / "answer_keys_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
