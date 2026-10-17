# Gap Finder: decisions

A record of product and architecture decisions, with the reason for each. Add new decisions at the bottom, and mark a decision "Superseded by #N" rather than deleting it.

Full build plan: `~/.claude/plans/buzzing-meandering-stonebraker.md`

---

## 1. Build Gap Finder
**Date:** 2026-10-14
**Decision:** Build Gap Finder (idea 16 in the Public-Data RAG Blueprints artifact). A parent or tutor enters a K–8 math problem their child is stuck on. The tool finds the earlier skill that is likely missing and links free lessons that teach it.
**Why:** It has the largest audience of the kids-focused ideas. A web search assistant can't answer the question, because the answer comes from walking a prerequisite graph and reading the child's answers to a short check. No free tool for parents does this yet (the Coherence Map and Learning Commons are aimed at teachers and developers).

## 2. Scope: all of K–8 math, Common Core plus state standards
**Date:** 2026-10-14
**Decision:** Cover all K–8 math standards. Map each state's standards to Common Core (crosswalks), and keep prerequisite edges on the Common Core layer.
**Why:** Parents think in terms of their own state's standards. Building prerequisites once on Common Core and reaching it from every state through crosswalks keeps the graph small (about 43k nodes, about 21% of the AuraDB Free limit).
**Risk:** Crosswalks will be weaker for states whose standards differ a lot from Common Core (for example Texas, Virginia, Indiana). The UI shows a confidence badge for these.

## 3. Stack
*Pinecone is planned for retirement in #21, once the #20 evals pass on Neo4j vector indexes.*
**Date:** 2026-10-14
**Decision:** OpenAI via `langchain-openai`, LangGraph, Neo4j AuraDB Free, Pinecone Starter, Streamlit, and a uv `pyproject.toml`. Embeddings are `text-embedding-3-small` shortened to 768 dimensions.
**Why:** This matches the course setup (`Mastering-Agentic-AI-Week1`) and the Streamlit + pytest layout in Project 1, and every service fits within its free tier.

## 4. Users are adults; nothing about the child is stored
**Date:** 2026-10-14
**Decision:** The parent or tutor runs the whole flow. There are no accounts, and no child data is saved. Session state is purged after 24 hours.
**Why:** This keeps the tool clear of children's-privacy rules such as COPPA and FERPA, and puts the result with the person who can act on it.

## 5. Problems and lessons are retrieved, never generated; CC BY content only
*The IM part of this decision is superseded by #10. Answer keys are covered by #16.*
**Date:** 2026-10-14
**Decision:** Check problems and lessons come only from a vetted CC BY bank, mainly Illustrative Mathematics. Non-commercial (NC) content such as Eureka Math is excluded. Every node and chunk carries its license and attribution.
**Why:** A made-up problem with a wrong answer key teaches the error. NC licenses would block any future paid tier.

## 6. Quality targets
**Date:** 2026-10-14
**Decision:** 95% faithfulness, 90% answer relevance, and at most 5 seconds per turn. The cyclic narrowing loop is capped at 2 rounds, and generation retries at most once.
**Why:** Parents act on the result right away, so wrong guidance is worse than an honest "we couldn't pinpoint it."

## 7. UI: a landing screen, then a guided 4-step wizard
**Date:** 2026-10-14
**Decision:**
- A short landing screen ("how it works" in three steps, then Start) leads into four steps: Problem → Confirm skill (only if the match is uncertain) → Check → Result.
- The **parent** types the child's answers.
- The check shows **one problem per screen** in large text, with a "They don't know" option and **no right/wrong feedback** during the check.
- The result screen is **stacked**: the likely gap with a confidence label, then a collapsible "What we saw", then 3 lesson cards, then the "Ask why" chat at the bottom.

**Why:** The typical setting is a parent on a phone at the kitchen table. A one-column wizard works on every screen size, is simple to build in Streamlit, and showing one problem at a time keeps the child relaxed.

## 8. Features in v1
**Date:** 2026-10-14
**Decision:** v1 includes the "Ask why" follow-up chat on the result screen. Its answers stay grounded in the retrieved lessons, it doesn't generate problems, and it's capped at about 10 turns.
**Deferred to v2:** photo input of the homework, Spanish, a printable practice sheet, a kid hand-off mode, and a skill-ladder visual.
**Why:** Keep v1 small and get the core diagnostic loop right first.

## 9. v1 covers math only
**Date:** 2026-10-14
**Decision:** v1 ingests math only. ELA, science, social studies, durable skills and the English-learner guidance framework are filtered out of the Learning Commons export (`scripts/extract_lc_math.py`). The raw export stays complete in `data/raw/` so other subjects can be added later without re-downloading.
**Why:** It keeps the graph, index and evaluation focused on the K–8 math diagnostic loop. Math-only cuts the export from 303k to 86k nodes and from 531k to 262k relationships.

## 10. IM content: first edition only
**Date:** 2026-10-14
**Decision:** Lessons and practice problems come only from IM K–12 Math, first edition (CC BY 4.0). IM v.360 lessons and problems are excluded, even in v1. The CC BY v.360 outline (scope and sequence) from Learning Commons may still be used for structure. Lesson cards use IM's exact attribution sentence and never the IM® name or logo as branding.
**Why:** The data audit found that IM v.360 is CC BY-NC 4.0. Anything built from it (chunks, embeddings, answer keys) would stay non-commercial and have to be rebuilt before v2.

## 11. Knowledge sources for the graph
**Date:** 2026-10-14
**Decision:**
- **Prerequisites:** the Coherence Map (CC0), from Learning Commons.
- **Misconceptions:** the Eedi Misconceptions Graph (CC BY 4.0), replacing LLM extraction from teacher notes.
- **"Why this skill" explanations:** the Common Core Progressions (CC BY 4.0).
- **Standards and crosswalks:** Learning Commons, with CASE Network 2 as the fallback. The Common Standards Project is dropped.

**Why:** Expert-authored, openly licensed records are more faithful than LLM-extracted ones, and every claim gets a citable source.
**Update (2026-10-14):** the Progressions are deferred because the host site is down. Until then, "why" explanations draw only on the Learning Commons skill-component and Coherence Map descriptions.
**Open item:** Eedi misconceptions link only to Eedi's own constructs. A mapping to US standards has to be built and checked by a person.

## 12. Common Core text handling
**Date:** 2026-10-14
**Decision:** Show the standards verbatim with the NGA/CCSSO copyright notice, and strip the examples, which the license excludes. Plain-language descriptions are labeled as Gap Finder's own. Sign the royalty-free Common Core commercial license before v2.
**Why:** The public license covers only uses that support the Common Core initiative and excludes the examples. The commercial license bars recasting the standards.

## 13. License tracking on every record
**Date:** 2026-10-14
**Decision:** Every node and chunk carries `license`, `source_url`, `attribution` and `v2_allowed`. A check fails the v2 build if any record has a license outside {CC BY 4.0, CC0, CCSS-licensed, state-permitted}. Source terms are tracked in `DATA_SOURCES.md`, and raw files in `data/raw/MANIFEST.json`.
**Why:** It makes the move from v1 to v2 a check rather than a re-audit.

## 14. Graph size fits the AuraDB Free tier
**Date:** 2026-10-14
**Decision:** The instance limit is confirmed at 200k nodes and 400k relationships. The plan is to load current frameworks for K–8 only (about 54k nodes and 151k relationships), leaving room for first-edition lessons and problems.
**Why:** Even the full math copy (86k nodes, 262k relationships) fits at 43% and 65%, so no data has to be dropped to fit.

## 15. Data is rebuilt from scripts, not committed
**Date:** 2026-10-14
**Decision:**
- `data/raw/`, `data/interim/` and `data/processed/` are git-ignored. Data flows one way: raw → interim → processed → Neo4j and Pinecone, with one script per step.
- Committed: the scripts, `data/raw/MANIFEST.json` (URLs and checksums), and a small test sample in `tests/fixtures/lc_math_sample/` with its own `ATTRIBUTION.md`. The sample has 993 nodes and 1,722 relationships, built by `scripts/make_fixture.py` around Common Core fractions for grades 4–6 plus the matching California standards.
- At the v1 release, publish the processed data as a single versioned download (a GitHub Release or a Hugging Face dataset) with full attribution, not in git history.

**Why:**
- The app reads from Neo4j and Pinecone at runtime, never from files.
- Large data files bloat git history and hit GitHub's file-size limits.
- Committing data redistributes it, which needs the full attribution set (one deliberate release is easier to get right).
- California adopted Common Core as written, which keeps the state-license question for the sample simple.

**Update (2026-10-16):** the data was briefly committed to a local branch for versioning, then taken back out before the first push, because the repo is public and four Learning Commons files are over GitHub's 100 MB limit. The data folders stay git-ignored and are kept on disk only. The answer-key reviews (`reviews.jsonl`) and the LLM cache (`llm_cache/`) are not backed up by git, so keep a separate copy of `data/interim/im_first_edition_pilot/`.

## 16. Answer keys are computed by us and checked by a person
**Date:** 2026-10-14
**Context:** first-edition IM problems are public and CC BY 4.0 on `im.kendallhunt.com`, but the solutions are behind a teacher login. Collecting them in bulk with a login isn't allowed under #10 and IM Terms §9.
**Decision:**
- Problems are still **retrieved** from the public first-edition pages. **Answer keys are derived by us.**
- **Scope:** only problems whose answer is a single number, fraction, decimal or multiple-choice option. Everything else stays lesson-only.
- **Method:**
  1. An LLM extracts the computation from the problem text.
  2. A math library (Python `fractions` / SymPy) computes the answer.
  3. A second, independent LLM solve must agree.
  4. Every disagreement goes to a person.
  5. A teacher checks a sample from each batch.
  A batch is used only if the sampled error rate is 0%.
- **Provenance on each key:** `answer_source: "derived"`, `method`, `verified_by` and `verified_at`. Keys that haven't been verified are never used in a check.
- **Pilot:** the grade 4–6 fraction problems (4.NF, 5.NF, 6.NS.A), which match the test sample.
- **Licensing:** problems keep IM's exact attribution, with "adapted" noted because we added answer keys. The derived keys are Gap Finder's own work. No login is used at any point.

**Why:** It unblocks the check step now, within the license decisions. A wrong key would teach the error, which is why there are two independent solves plus a person's review.
**Reviewer:** Sapna (teacher). Reviews were entered by Vivek.
**Pilot result (2026-10-14):**
- 228 problems split into 429 parts. 211 parts agreed, 8 disagreed and 2 couldn't be computed.
- Sapna reviewed all 10 open items (4 corrected) and a random sample of 40 agreed keys (0 wrong), so the batch passed.
- 221 verified keys are in `answer_keys_verified.jsonl`.
- 13 of 18 fraction standards have 2 or more verified keys. Thin: 3.NF.A.2, 5.NF.B.5, 5.NF.B.6, and 4.NF.C.6–7 (outside the pilot).

## 17. Homework is matched to Common Core first; state wording is for display
**Date:** 2026-10-14
**Decision:** The agent matches a homework problem directly to a Common Core standard and runs the prerequisite walk on the Common Core layer. The crosswalk is used only to show the parent their own state's wording, with a confidence badge. This replaces the plan's order of matching to a state standard first and then crosswalking.
**Why:**
- After loading the graph, crosswalks covered 43 of 51 jurisdictions. Indiana, Wyoming, Nebraska, Minnesota, Mississippi, Maryland, South Carolina and Montana have none.
- Some states word standards differently enough that the key link is missing. Texas's 6th-grade "divide positive rational numbers" has no crosswalk to 6.NS.A.1.
- Matching through the state first would fail in exactly those cases.

**Related:** the Coherence Map links whole standards while problems are tagged to sub-standards, so graph lookups include sub-standards (`gapfinder/graph/queries.py`).

## 18. How the agent is built
**Date:** 2026-10-15
**Decision:**
- **Code:** a LangGraph `StateGraph` in `gapfinder/agent/`. The steps live in one `nodes.py`, not one file per node as the plan suggested, because they share small helpers. The gap rules are in `scoring.py` and are plain Python. Routing is plain Python too.
- **Pauses:** `confirm_skill` and `await_answers` are LangGraph interrupts. Progress is saved per browser session in `data/sessions.sqlite`, which is git-ignored.
- **The check** covers the homework skill itself plus up to 3 earlier skills that have at least 2 verified problems. At most 2 rounds. Answers are sent once per round.
- **"Ask why"** runs separately (`followup.py`), reads the saved session, and appends to it. Cited lessons must come from its context and exist in the graph.
- **Models:** `gpt-4.1-mini` for describing the skill, picking the standard and grounding checks. `gpt-4.1` for writing the result and chat answers. Both can be changed in `.env`. They're fast, non-reasoning models, to stay inside the 5-second budget.

**Measured (2026-10-15, connections already open):**
- request 1 (to the check): 2.7–2.8 s
- request 3 (answers to result): 2.4–3.1 s
- "Ask why": 2.1–2.3 s

The first request in a new process takes 3.9–5.7 s while connections open, so the app must open them at startup.

**Tested:** 30 unit tests cover the answer checker, scoring and routing. Two end-to-end runs both reached the expected gap with high confidence and no rewrite:
- grade 6, Texas, 3/4 ÷ 1/8 → 5.NF.B.7
- grade 4, California, compare 2/3 and 3/5 → 4.NF.A.1

## 19. Wizard UI and the "can't check yet" outcome
**Date:** 2026-10-15
**Decision:**
- **Coverage is stated upfront.** The landing screen and step 1 say "Right now: fraction homework, grades 3–6". When a matched skill and its earlier skills have no verified problems, the agent ends with a **"can't check this skill yet"** result (`cannot_check` node) instead of "no earlier gap".
- **Waiting:** live progress steps that tick off as each agent step finishes.
- **Skill names:** the official Common Core text with its code, cut short with "Show full text". Plain-language names may come later.
- **Math display:** rendered math, converted from the source's LaTeX.
- **Together, parent types** (confirms #7, keeps kid mode deferred per #8):
  - The landing screen says "Do this together: you and your child, about 5 minutes, pencil and paper."
  - A "Time to check together!" handover screen follows the skill match, with role cards for the child and the parent.
  - Every question shows "Child solves on paper → You type their answer".
- **Look:** kid-friendly and playful.
  - The landing illustration is **option B, the skill staircase** from Kindergarten to Grade 8 with one missing step, and the logo is a small staircase to match.
  - Progress bars are drawn as fraction tiles. Tilly the tile character appears at key moments.
  - Headings in Fredoka, body text in Lexend, on a graph-paper background.
- **Mockups:** the "Gap Finder Wizard Mockups" design canvas.

**Why:** chosen by Vivek in the UI brainstorm and mockup review (2026-10-15). The fraction-only landing visual was replaced so the app doesn't look fraction-only when more topics are added.

## 20. V1 evaluation plan
**Date:** 2026-10-15
**Decision:** V1 isn't released until 16 "must" evals pass. The full list is in Phase 5 of the build plan (`~/.claude/plans/buzzing-meandering-stonebraker.md`).

**Datasets:**
- **D1:** about 80 IM first-edition problems as homework inputs. Each problem's own parts are held out of the check during its run.
- **D2:** simulated children whose answer patterns give a known gap.
- **D3:** out-of-scope, non-math and injection inputs.
- **D4:** 30 parent questions for Ask why.

**Evals:**
- answer keys and data integrity
- standard matching (≥ 80% top-1, ≥ 95% recall@8) and confidence calibration
- scope handling
- gap diagnosis (≥ 90% clean, ≥ 80% noisy) and prerequisite recall (≥ 85%)
- result faithfulness (≥ 95%) and relevance and tone (≥ 90%)
- Ask why (grounded, relevant, declines correctly)
- grader effectiveness
- privacy and injection
- latency (p95 ≤ 5 s), cost, reliability
- judge calibration with Sapna (≥ 85% agreement)

The family pilot (5 pairs) comes later, before public launch.

**Judging:** an AI judge (`gpt-5.5`, different from the runtime models) scores the written output. Sapna rates 30 results and 30 answers once, to calibrate it.

**Why:** chosen by Vivek. The golden set reuses IM bank problems (fastest, with low leakage because matching searches the standards index, not problem text). The judge is AI, checked by a teacher. Repeatable evals are needed before widening the data or releasing.

## 21. Full K–8 math fits AuraDB Free, and Neo4j stays the core store
**Date:** 2026-10-16
**Context:** Vivek wants to build for scale and use the graph more fully: Eedi misconceptions, learning paths, the full IM catalogue, and visual review of the graph. The question was whether the free tier holds all of K–8 math, not just fractions.
**Decision:**
- Stay on AuraDB Free for all of K–8 math. The standards layer already covers every K–8 topic area (`build_graph.py` keeps all current K–8 frameworks and 6,445 skill components). Only problems and lessons are limited to the fractions pilot.
- **Estimated size at full K–8 math** (limits from #14: 200k nodes, 400k relationships):

  | Layer | Nodes | Relationships |
  |---|---|---|
  | Today (measured) | 33,683 | 91,330 |
  | Eedi misconceptions and constructs (measured in the export) | +10,375 | +19,294 |
  | Construct → Common Core mapping | – | +2–5k |
  | IM first edition K–8 lessons (estimate; the v.360 K–8 outline has 1,639) | +~1,500 | +~5k |
  | IM first edition K–8 problem parts (estimate from the pilot) | +~6–10k | +~10–20k |
  | Problem parts → skill components | – | +~15–25k |
  | Extra prerequisite edges (IM sequence, Progressions) | – | +~3–5k |
  | **Total** | **~52–56k (26–28%)** | **~150–170k (37–42%)** |

- Keep Neo4j as the core store and plan to retire Pinecone by moving embeddings onto the nodes in Neo4j vector indexes. Pinecone is removed only after the matching and latency evals in #20 pass with the same scores.
- Store vectors as float32 with `db.create.setNodeVectorProperty`. That's about 20–25k vectors, or 60–80 MB at 768 dimensions. Shortening to 512 dimensions is the fallback if storage gets tight.

**Why:**
- Even if the IM estimates are 2× too low, the graph stays under 35% of the node limit and 50% of the relationship limit.
- With one store, the ids agree everywhere, there's one loader, and a single query can filter by the graph and rank by similarity.
- The graph use cases are blocked by missing data, not by the database. Eedi constructs have no link to US standards (#11), the Coherence Map has only 454 prerequisite edges and touches 247 of the 397 K–8 Common Core standards, and answer keys need a person's review (#16).

**Risks and checks:**
- Free-tier terms other than the node and relationship limits are unconfirmed and need checking in the Aura console: storage and memory, vector index support, and pausing when idle. A paused instance breaks the 5-second budget on the first request.
- There's no Graph Data Science library on the free tier. Compute centrality or paths offline (networkx) and write the scores back as properties, or move to a paid tier.
- There's one instance and no backups. This is acceptable because the data is rebuilt from scripts (#15).
- All subjects (303k nodes, 531k relationships) don't fit, so adding other subjects means a paid tier.
