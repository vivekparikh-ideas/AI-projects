// Uniqueness constraints (each also creates an index on id).
CREATE CONSTRAINT framework_id IF NOT EXISTS FOR (n:Framework) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT standard_id IF NOT EXISTS FOR (n:Standard) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT skill_id IF NOT EXISTS FOR (n:SkillComponent) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT lesson_id IF NOT EXISTS FOR (n:Lesson) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT problem_id IF NOT EXISTS FOR (n:Problem) REQUIRE n.id IS UNIQUE;

// Lookups used by the agent.
CREATE INDEX standard_code IF NOT EXISTS FOR (n:Standard) ON (n.code);
CREATE INDEX standard_jurisdiction IF NOT EXISTS FOR (n:Standard) ON (n.jurisdiction);
