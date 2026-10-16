"""Every Cypher query the agent runs. Parameterized templates only; no model-written Cypher.

Problems are tagged to the most specific standard (for example 4.NF.B.4.c), while the Coherence Map
links whole standards (4.NF.B.4). Lookups by standard therefore include sub-standards via HAS_CHILD.
"""
from neo4j import Driver

# Common Core targets for a state standard, strongest crosswalk first.
CROSSWALK = """
MATCH (s:Standard {id: $state_standard_id})-[x:CROSSWALKS_TO]->(c:Standard {is_ccss: true})
RETURN c.code AS code, c.text AS text, x.jaccard AS jaccard
ORDER BY x.jaccard DESC
"""

# State wording for a Common Core standard in one jurisdiction (for display only).
STATE_WORDING = """
MATCH (s:Standard {jurisdiction: $jurisdiction})-[x:CROSSWALKS_TO]->(:Standard {code: $code, is_ccss: true})
RETURN s.code AS code, s.text AS text, x.jaccard AS jaccard
ORDER BY x.jaccard DESC LIMIT 1
"""

# Prerequisite candidates up to 2 steps back, with how many verified problems each has.
PREREQUISITES = """
MATCH path = (p:Standard {is_ccss: true})-[:BUILDS_TOWARDS*1..2]->(:Standard {code: $code, is_ccss: true})
OPTIONAL MATCH (p)-[:HAS_CHILD*0..2]->(:Standard)<-[:ASSESSES]-(prob:Problem)
WITH p, min(length(path)) AS hops, count(DISTINCT prob) AS problems
RETURN p.code AS code, p.text AS text, p.grades AS grades, hops, problems
ORDER BY hops, problems DESC, code
LIMIT $limit
"""

# Verified, checkable problems for a standard or its sub-standards.
CHECK_PROBLEMS = """
MATCH (:Standard {code: $code, is_ccss: true})-[:HAS_CHILD*0..2]->(s:Standard)<-[:ASSESSES]-(p:Problem)
WHERE p.checkable AND p.answer_key IS NOT NULL AND NOT p.id IN $exclude
RETURN p.id AS id, p.text AS text, p.kind AS kind, p.answer_key AS answer_key,
       s.code AS standard, p.source_url AS source_url, p.attribution AS attribution
ORDER BY p.id
LIMIT $limit
"""

# Lessons that address a standard or its sub-standards.
LESSONS = """
MATCH (:Standard {code: $code, is_ccss: true})-[:HAS_CHILD*0..2]->(s:Standard)<-[:ADDRESSES]-(l:Lesson)
RETURN DISTINCT l.id AS id, l.title AS title, l.grade AS grade, l.unit AS unit, l.lesson AS lesson,
       l.url AS url, l.attribution AS attribution
ORDER BY l.grade, toInteger(l.unit), toInteger(l.lesson)
LIMIT $limit
"""

# One Common Core standard by code.
STANDARD = """
MATCH (s:Standard {code: $code, is_ccss: true})
RETURN s.code AS code, s.text AS text, s.grades AS grades
LIMIT 1
"""

# Several Common Core standards by code, in one round trip.
STANDARDS = """
UNWIND $codes AS code
MATCH (s:Standard {code: code, is_ccss: true})
RETURN s.code AS code, s.text AS text, s.grades AS grades
"""

# Skills a standard builds towards (used for "Ask why" context).
NEXT_SKILLS = """
MATCH (:Standard {code: $code, is_ccss: true})-[:BUILDS_TOWARDS]->(n:Standard {is_ccss: true})
RETURN n.code AS code, n.text AS text
ORDER BY n.code LIMIT $limit
"""

# States (and DC) with a current math framework, for the state picker.
JURISDICTIONS = """
MATCH (f:Framework {is_ccss: false})
RETURN DISTINCT f.jurisdiction AS jurisdiction
ORDER BY jurisdiction
"""

# Grader check: which of these ids really exist.
EXISTING_IDS = """
UNWIND $ids AS id
OPTIONAL MATCH (n {id: id})
RETURN id, n IS NOT NULL AS exists
"""


def run(driver: Driver, query: str, **params) -> list[dict]:
    return [r.data() for r in driver.execute_query(query, params).records]


def prerequisites(driver: Driver, code: str, limit: int = 4) -> list[dict]:
    return run(driver, PREREQUISITES, code=code, limit=limit)


def check_problems(driver: Driver, code: str, limit: int = 2, exclude: list[str] | None = None) -> list[dict]:
    return run(driver, CHECK_PROBLEMS, code=code, limit=limit, exclude=exclude or [])


def lessons(driver: Driver, code: str, limit: int = 3) -> list[dict]:
    return run(driver, LESSONS, code=code, limit=limit)


def state_wording(driver: Driver, jurisdiction: str, code: str) -> dict | None:
    rows = run(driver, STATE_WORDING, jurisdiction=jurisdiction, code=code)
    return rows[0] if rows else None


def standard(driver: Driver, code: str) -> dict | None:
    rows = run(driver, STANDARD, code=code)
    return rows[0] if rows else None


def standards(driver: Driver, codes: list[str]) -> dict[str, dict]:
    return {r["code"]: r for r in run(driver, STANDARDS, codes=codes)}


def next_skills(driver: Driver, code: str, limit: int = 3) -> list[dict]:
    return run(driver, NEXT_SKILLS, code=code, limit=limit)


def jurisdictions(driver: Driver) -> list[str]:
    return [r["jurisdiction"] for r in run(driver, JURISDICTIONS) if r["jurisdiction"]]


def missing_ids(driver: Driver, ids: list[str]) -> list[str]:
    return [r["id"] for r in run(driver, EXISTING_IDS, ids=ids) if not r["exists"]]
