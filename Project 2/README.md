# Gap Finder

Find the math skill behind tonight's homework. A parent types the problem their child is stuck on. Gap Finder matches it to a Common Core standard, runs a short check with the child using teacher-reviewed questions, finds the earlier skill that's missing, and links free lessons for it.

Free and open source. No accounts, and nothing about the child is saved.

**Coverage today:** fraction homework, grades 3–6.

## Run it

```bash
uv sync
cp .env.example .env    # then fill in the keys below
uv run streamlit run app.py
```

`.env` needs these values: `OPENAI_API_KEY`, `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` and `PINECONE_API_KEY`. Optional overrides: `GAPFINDER_MODEL_FAST`, `GAPFINDER_MODEL_WRITE` and `PINECONE_INDEX`.

## How it works

- **The agent** is a LangGraph state machine in `gapfinder/agent/`. It pauses for the parent twice, to confirm the skill and to run the check, and saves progress per browser session in `data/sessions.sqlite`. Saved sessions are deleted after 24 hours.
- **Knowledge graph (Neo4j):**
  - Common Core and state standards, crosswalks and Coherence Map prerequisites (from Learning Commons)
  - first-edition IM lessons
  - verified check problems
- **Vectors (Pinecone):** standards, skill components, problems and lessons, used to match homework to a standard and to rank lessons.
- **The app** is Streamlit (`app.py`, `ui/`). Its design is recorded in `decisions.md` #19.

## Rebuild the data

All data is rebuilt from scripts. Nothing under `data/` is committed except `data/raw/MANIFEST.json`.

```bash
# 1. Download the Learning Commons export into data/raw/ (URLs and checksums: data/raw/MANIFEST.json)
uv run python -I scripts/extract_lc_math.py data/raw/learning_commons_v1.15.0   # math-only copy
uv run python scripts/collect_im_pilot.py      # public first-edition IM pages, one request every 2 s
uv run python scripts/parse_im_pilot.py        # problem and lesson records
uv run python scripts/derive_answer_keys.py    # answer keys (decision #16)
uv run streamlit run scripts/review_answer_keys.py   # teacher review, then finalize
uv run python -m gapfinder.ingest.build_graph
uv run python -m gapfinder.graph.load
uv run python -m gapfinder.vectors.index
```

## Tests

```bash
uv run pytest                          # unit tests: answers, scoring, routing, sessions
uv run python scripts/demo_agent.py    # one agent session with a simulated child
uv run python scripts/smoke_app.py     # clicks through the real app (live services)
```

## Licenses and attribution

Every data source, its license and its required attribution are recorded in `DATA_SOURCES.md`. In short:
- Learning Commons Knowledge Graph: CC BY 4.0, with the Coherence Map under CC0.
- IM K–12 Math, first edition: CC BY 4.0. Lessons and problems are "Based on IM® K–12 Math authored by Illustrative Mathematics and licensed under CC BY 4.0."
- Common Core text: © Copyright 2010. National Governors Association Center for Best Practices and Council of Chief State School Officers. All rights reserved.
