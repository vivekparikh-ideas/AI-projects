"""Teacher review of derived answer keys (decisions.md #16).

Queue: every 'disagree' and 'compute_error' part, plus a fixed random sample of 'agreed' parts.
The batch passes only if no sampled 'agreed' key is marked wrong. Finalizing writes
answer_keys_verified.jsonl, the only file later steps may use.

Run: uv run streamlit run scripts/review_answer_keys.py
"""
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
PILOT_DIR = ROOT / "data" / "interim" / "im_first_edition_pilot"
REVIEWS = PILOT_DIR / "reviews.jsonl"
VERIFIED = PILOT_DIR / "answer_keys_verified.jsonl"
SAMPLE_SIZE = 40
SEED = 16

VERDICTS = {
    "correct": "The answer key is correct",
    "wrong": "The answer key is wrong (I'll enter the right one)",
    "unsuitable": "Not suitable for a quick check",
}


@st.cache_data
def load():
    parts = [json.loads(line) for line in open(PILOT_DIR / "answer_keys.jsonl", encoding="utf-8")]
    problems = {p["id"]: p for p in map(json.loads, open(PILOT_DIR / "problems.jsonl", encoding="utf-8"))}
    must = [p for p in parts if p["status"] in ("disagree", "compute_error")]
    agreed = sorted((p for p in parts if p["status"] == "agreed"), key=lambda p: p["part_id"])
    sample = random.Random(SEED).sample(agreed, min(SAMPLE_SIZE, len(agreed)))
    return parts, problems, must + sample, {p["part_id"] for p in sample}


def load_reviews() -> dict:
    if not REVIEWS.exists():
        return {}
    out = {}
    for line in open(REVIEWS, encoding="utf-8"):
        r = json.loads(line)
        out[r["part_id"]] = r
    return out


def save_review(review: dict) -> None:
    with open(REVIEWS, "a", encoding="utf-8") as f:
        f.write(json.dumps(review, ensure_ascii=False) + "\n")


def finalize(parts, reviews, sampled_ids, batch_passes) -> int:
    rows = []
    for p in parts:
        r = reviews.get(p["part_id"])
        if r:
            if r["verdict"] == "unsuitable":
                continue
            # A typed answer always wins, even if the reviewer chose "correct".
            key = r["corrected_answer"] or (p["computed"] if r["verdict"] == "correct" else None)
            if not key:
                continue
            verification = {"verified_by": r["reviewer"], "verified_at": r["reviewed_at"], "verification": "individual"}
            standard, standard_verified = r["standard"], True
        elif p["status"] == "agreed" and batch_passes:
            key = p["computed"]
            sample_reviews = [reviews[i] for i in sampled_ids if i in reviews]
            verification = {"verified_by": sample_reviews[0]["reviewer"], "verified_at": max(x["reviewed_at"] for x in sample_reviews),
                            "verification": f"batch sample ({len(sample_reviews)} of {len(sampled_ids)} agreed keys checked, 0 wrong)"}
            standard, standard_verified = p["standard"], False
        else:
            continue
        rows.append({**{k: p[k] for k in ("part_id", "problem_id", "label", "part_text", "grade", "source_url",
                                          "candidate_standards", "method")},
                     # The key decides the kind: a reviewer's typed value overrides a mislabeled comparison.
                     "kind": "comparison" if key in ("<", ">", "=") else "value",
                     "answer_key": key, "answer_source": "derived", "standard": standard,
                     "standard_verified": standard_verified, **verification})
    with open(VERIFIED, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


st.set_page_config(page_title="Answer key review", layout="centered")
parts, problems, queue, sampled_ids = load()
reviews = load_reviews()

st.title("Answer key review")
st.caption("Gap Finder pilot · grade 3–6 fractions · IM K–12 Math first edition (CC BY 4.0)")
reviewer = st.text_input("Your initials", key="reviewer", help="Saved with each review as the verifier.")

done = sum(1 for p in queue if p["part_id"] in reviews)
st.progress(done / len(queue), text=f"{done} of {len(queue)} reviewed "
            f"({len(queue) - len(sampled_ids)} need a decision, {len(sampled_ids)} are a random sample of agreed keys)")

tab_review, tab_summary = st.tabs(["Review", "Summary and finalize"])

with tab_review:
    if "idx" not in st.session_state:
        st.session_state.idx = next((i for i, p in enumerate(queue) if p["part_id"] not in reviews), 0)
    idx = st.session_state.idx
    item = queue[idx]
    problem = problems[item["problem_id"]]
    prior = reviews.get(item["part_id"])

    why = "Random sample of an agreed key" if item["part_id"] in sampled_ids else {
        "disagree": "The two independent solves disagree", "compute_error": "The calculation could not be computed"}[item["status"]]
    st.subheader(f"Item {idx + 1} of {len(queue)}")
    st.caption(f"{why} · Grade {item['grade']} · [source page]({item['source_url']})")

    with st.expander("Full problem from the curriculum", expanded=False):
        st.markdown(problem["text"].replace("\n", "  \n"))
        for img in problem["images"]:
            if img.get("src"):
                st.image(img["src"], caption=img["alt"] or None, width=360)
            if img.get("description"):
                st.caption(img["description"])

    st.markdown("**Question part to check**")
    st.info(item["part_text"])
    c1, c2 = st.columns(2)
    c1.metric("Computed answer key", item["computed"] or "—")
    c2.metric("Independent solve", item["solver_answer"] or "—")
    if item.get("note"):
        st.caption(f"Note: {item['note']}")

    with st.form(key=f"form_{item['part_id']}"):
        verdict = st.radio("Your decision", list(VERDICTS), format_func=VERDICTS.get,
                           index=list(VERDICTS).index(prior["verdict"]) if prior else 0)
        corrected = st.text_input("Correct answer (only if the key is wrong)", value=(prior or {}).get("corrected_answer") or "",
                                  placeholder="e.g. 3/4, 1 1/2, 0.6, or < > =")
        options = item["candidate_standards"] or [item["standard"]]
        default_std = (prior or {}).get("standard") or item["standard"]
        standard = st.selectbox("Standard this part practices", options,
                                index=options.index(default_std) if default_std in options else 0)
        submitted = st.form_submit_button("Save and next", type="primary", disabled=not reviewer)
    if not reviewer:
        st.caption("Enter your initials above to save reviews.")
    if submitted:
        if verdict == "wrong" and not corrected.strip():
            st.error("Enter the correct answer, or choose a different decision.")
        else:
            save_review({"part_id": item["part_id"], "verdict": verdict, "corrected_answer": corrected.strip() or None,
                         "standard": standard, "reviewer": reviewer.strip(),
                         "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            st.session_state.idx = min(idx + 1, len(queue) - 1)
            st.rerun()

    b1, b2 = st.columns(2)
    if b1.button("← Previous", disabled=idx == 0):
        st.session_state.idx -= 1
        st.rerun()
    if b2.button("Skip →", disabled=idx == len(queue) - 1):
        st.session_state.idx += 1
        st.rerun()

with tab_summary:
    sampled_done = [reviews[i] for i in sampled_ids if i in reviews]
    wrong = [r for r in sampled_done if r["verdict"] == "wrong"]
    must_open = [p for p in queue if p["part_id"] not in sampled_ids and p["part_id"] not in reviews]
    st.metric("Agreed keys sampled and reviewed", f"{len(sampled_done)} of {len(sampled_ids)}")
    st.metric("Sampled keys marked wrong", len(wrong))
    st.metric("Disagreements still open", len(must_open))
    batch_passes = len(sampled_done) == len(sampled_ids) and not wrong
    if wrong:
        st.error("The batch fails: a sampled agreed key was wrong. Agreed keys can't be used without individual review.")
    elif not batch_passes:
        st.warning("Review the whole sample before finalizing.")
    else:
        st.success("The batch passes: every sampled agreed key was correct.")
    if st.button("Finalize verified answer keys", disabled=not batch_passes or bool(must_open)):
        n = finalize(parts, load_reviews(), sampled_ids, batch_passes)
        st.success(f"Wrote {n} verified answer keys to {VERIFIED.relative_to(ROOT)}.")
