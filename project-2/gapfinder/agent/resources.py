"""Shared clients, created once per process."""
from functools import lru_cache

from langchain_openai import ChatOpenAI
from neo4j import GraphDatabase

from gapfinder.config import MODEL_FAST, MODEL_WRITE, neo4j_settings


@lru_cache(maxsize=1)
def neo4j():
    uri, auth = neo4j_settings()
    return GraphDatabase.driver(uri, auth=auth)


@lru_cache(maxsize=1)
def fast_model() -> ChatOpenAI:
    return ChatOpenAI(model=MODEL_FAST, temperature=0, timeout=20)


@lru_cache(maxsize=1)
def write_model() -> ChatOpenAI:
    return ChatOpenAI(model=MODEL_WRITE, temperature=0.2, timeout=30)
