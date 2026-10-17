"""Paths, model names and limits shared across Gap Finder."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
LC_MATH = DATA / "interim" / "learning_commons_v1.15.0_math"
IM_PILOT = DATA / "interim" / "im_first_edition_pilot"
PROCESSED_GRAPH = DATA / "processed" / "graph"

SESSIONS_DB = DATA / "sessions.sqlite"

# Agent models. Fast, non-reasoning models keep each request inside the 5-second budget.
MODEL_FAST = os.environ.get("GAPFINDER_MODEL_FAST", "gpt-4.1-mini")   # describe skill, pick standard, grade
MODEL_WRITE = os.environ.get("GAPFINDER_MODEL_WRITE", "gpt-4.1")      # result text and Ask why answers
CONFIDENCE_THRESHOLD = 0.6
MAX_ROUNDS = 2
MAX_PREREQS = 3
PROBLEMS_PER_SKILL = 2
MAX_CHAT_TURNS = 10

K8_GRADES = {"K", "KG", "0", "1", "2", "3", "4", "5", "6", "7", "8"}
CCSS_JURISDICTION = "Multi-State"
CCSS_NOTICE = ("© Copyright 2010. National Governors Association Center for Best Practices "
               "and Council of Chief State School Officers. All rights reserved.")


def neo4j_settings() -> tuple[str, tuple[str, str]]:
    return os.environ["NEO4J_URI"], (os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])


def pinecone_settings() -> tuple[str, str, str, str]:
    """API key, index name, cloud and region. Starter (free) indexes run on AWS us-east-1."""
    return (os.environ["PINECONE_API_KEY"], os.environ.get("PINECONE_INDEX", "gap-finder"),
            os.environ.get("PINECONE_CLOUD", "aws"), os.environ.get("PINECONE_REGION", "us-east-1"))
