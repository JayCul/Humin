"""Thin CockroachDB connection layer.

Uses psycopg2 directly (CockroachDB is Postgres wire-compatible) with a small
connection pool and CockroachDB's recommended transaction retry wrapper,
since distributed transactions can raise serialization errors under
contention that a client is expected to retry.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Callable, TypeVar

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool

from app.config import get_settings

logger = logging.getLogger("humin.db")

T = TypeVar("T")

_pool: SimpleConnectionPool | None = None


def _get_pool() -> SimpleConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        if not settings.cockroachdb_url:
            raise RuntimeError(
                "COCKROACHDB_URL is not set. Either configure a real cluster "
                "or leave USE_MOCK_DB=true to run against the in-memory repository."
            )
        _pool = SimpleConnectionPool(1, 10, dsn=settings.cockroachdb_url)
    return _pool


@contextmanager
def get_cursor(commit: bool = False):
    pool = _get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = False
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        pool.putconn(conn)


def run_with_retry(fn: Callable[[], T], max_retries: int = 5) -> T:
    """CockroachDB best practice: client-side retry on serialization errors
    (SQLSTATE 40001) for transactions that don't use the internal SAVEPOINT
    cockroach_restart retry loop."""
    for attempt in range(max_retries):
        try:
            return fn()
        except psycopg2.errors.SerializationFailure:
            if attempt == max_retries - 1:
                raise
            backoff = min(0.1 * (2**attempt), 2.0)
            logger.warning("Serialization failure, retrying in %.2fs (attempt %d)", backoff, attempt + 1)
            time.sleep(backoff)
    raise RuntimeError("unreachable")


def vector_literal(embedding: list[float]) -> str:
    """CockroachDB VECTOR columns accept a bracketed literal, same as pgvector."""
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


def run_schema(schema_path: str) -> None:
    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()
    with get_cursor(commit=True) as cur:
        cur.execute(sql)
