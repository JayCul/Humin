"""Repository layer - Humin's memory access.

Two implementations behind the same interface:

- `CockroachRepository`   talks to a real CockroachDB Cloud cluster, including
                          a native `VECTOR` column + vector index for
                          semantic recall (the "Distributed Vector Indexing"
                          hackathon tool).
- `InMemoryRepository`    a dependency-free stand-in so the full agent loop
                          runs offline/without credentials. Cosine similarity
                          is computed in Python instead of via the vector
                          index, but the interface - and therefore the
                          orchestrator logic - is identical either way.

`get_repository()` picks one based on `Settings.use_mock_db`.
"""
from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Protocol

from app.config import get_settings
from app.db import mcp_client
from app.db.connection import get_cursor, run_with_retry, vector_literal

logger = logging.getLogger("humin.db")


# --------------------------------------------------------------------------
# Shared record shapes
# --------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


class Repository(Protocol):
    def create_campaign(self, **kwargs: Any) -> dict: ...
    def get_campaigns(self) -> list[dict]: ...
    def get_campaign(self, campaign_id: str) -> dict | None: ...
    def update_campaign_status(self, campaign_id: str, status: str) -> dict: ...

    def add_content_piece(self, **kwargs: Any) -> dict: ...
    def get_latest_content(self, campaign_id: str) -> dict | None: ...
    def get_pending_draft(self, campaign_id: str) -> dict | None: ...
    def get_content(self, campaign_id: str, content_id: str) -> dict | None: ...
    def update_content_status(self, content_id: str, status: str, **kwargs: Any) -> dict: ...
    def update_content_image(
        self, content_id: str, image_data_url: str, image_source: str, image_prompt: str | None = None
    ) -> dict: ...
    def search_similar_content(
        self, embedding: list[float], exclude_campaign_id: str | None, limit: int
    ) -> list[dict]: ...

    def record_performance(self, **kwargs: Any) -> dict: ...
    def get_performance_history(self, campaign_id: str) -> list[dict]: ...

    def log_decision(self, **kwargs: Any) -> dict: ...
    def get_decisions(self, campaign_id: str) -> list[dict]: ...

    def add_trend_signal(self, **kwargs: Any) -> dict: ...
    def get_recent_trend_signals(self, campaign_id: str, limit: int) -> list[dict]: ...

    def reset_all(self) -> None: ...


def _similarity_sql_inline(vec: str, exclude_campaign_id: str | None, limit: int) -> str:
    """Same vector-similarity query as `search_similar_content`'s direct-
    driver path, but with values inlined as literals - an MCP tool call
    takes a plain SQL string, not psycopg2's %s parameter substitution.
    `vec` is a numeric-formatted string we generated ourselves
    (`vector_literal`) and `exclude_campaign_id` is one of our own UUIDs,
    not raw user text, so literal interpolation here is safe."""
    # Only published content is real precedent — a draft is unreviewed (may
    # never even go live) and a discarded one was explicitly rejected, so
    # neither belongs in what the agent recalls as "what worked before".
    where_clause = "cp.embedding IS NOT NULL AND cp.status = 'published'"
    if exclude_campaign_id:
        where_clause += f" AND cp.campaign_id != '{exclude_campaign_id}'"
    return f"""
        SELECT cp.id, cp.campaign_id, c.name AS campaign_name, c.region,
               cp.headline, cp.body, cp.channel, cp.cycle,
               cp.embedding <-> '{vec}' AS distance,
               pm.ctr, pm.conversions, pm.spend_usd, pm.impressions
        FROM content_pieces cp
        JOIN campaigns c ON c.id = cp.campaign_id
        LEFT JOIN LATERAL (
            SELECT ctr, conversions, spend_usd, impressions
            FROM performance_metrics
            WHERE content_id = cp.id
            ORDER BY recorded_at DESC
            LIMIT 1
        ) pm ON true
        WHERE {where_clause}
        ORDER BY distance ASC
        LIMIT {int(limit)}
    """


# --------------------------------------------------------------------------
# CockroachDB implementation
# --------------------------------------------------------------------------

class CockroachRepository:
    def create_campaign(self, **kwargs: Any) -> dict:
        def _do():
            with get_cursor(commit=True) as cur:
                cur.execute(
                    """
                    INSERT INTO campaigns (name, product, audience_segment, goal, tone, region, budget_usd, approval_mode)
                    VALUES (%(name)s, %(product)s, %(audience_segment)s, %(goal)s, %(tone)s, %(region)s, %(budget_usd)s, %(approval_mode)s)
                    RETURNING *
                    """,
                    {
                        **kwargs,
                        "budget_usd": kwargs.get("budget_usd"),
                        "approval_mode": kwargs.get("approval_mode") or "autonomous",
                    },
                )
                return dict(cur.fetchone())

        return run_with_retry(_do)

    def get_campaigns(self) -> list[dict]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM campaigns ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]

    def get_campaign(self, campaign_id: str) -> dict | None:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM campaigns WHERE id = %s", (campaign_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def update_campaign_status(self, campaign_id: str, status: str) -> dict:
        def _do():
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE campaigns SET status = %s WHERE id = %s RETURNING *",
                    (status, campaign_id),
                )
                return dict(cur.fetchone())

        return run_with_retry(_do)

    _CONTENT_COLUMNS = (
        "id, campaign_id, cycle, version, channel, headline, body, status, "
        "image_data_url, image_source, image_prompt, created_at"
    )

    def add_content_piece(self, **kwargs: Any) -> dict:
        embedding = kwargs.pop("embedding")
        kwargs["embedding"] = vector_literal(embedding) if embedding else None
        kwargs.setdefault("status", "published")
        kwargs.setdefault("image_data_url", None)
        kwargs.setdefault("image_source", None)
        kwargs.setdefault("image_prompt", None)

        def _do():
            with get_cursor(commit=True) as cur:
                cur.execute(
                    f"""
                    INSERT INTO content_pieces
                        (campaign_id, cycle, version, channel, headline, body, embedding, generated_by_decision_id,
                         status, image_data_url, image_source, image_prompt)
                    VALUES
                        (%(campaign_id)s, %(cycle)s, %(version)s, %(channel)s, %(headline)s, %(body)s,
                         %(embedding)s, %(generated_by_decision_id)s, %(status)s,
                         %(image_data_url)s, %(image_source)s, %(image_prompt)s)
                    RETURNING {self._CONTENT_COLUMNS}
                    """,
                    kwargs,
                )
                return dict(cur.fetchone())

        return run_with_retry(_do)

    def get_latest_content(self, campaign_id: str) -> dict | None:
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT {self._CONTENT_COLUMNS}
                FROM content_pieces WHERE campaign_id = %s AND status = 'published'
                ORDER BY cycle DESC, version DESC LIMIT 1
                """,
                (campaign_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_pending_draft(self, campaign_id: str) -> dict | None:
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT {self._CONTENT_COLUMNS}
                FROM content_pieces WHERE campaign_id = %s AND status = 'draft'
                ORDER BY cycle DESC, version DESC LIMIT 1
                """,
                (campaign_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_content(self, campaign_id: str, content_id: str) -> dict | None:
        with get_cursor() as cur:
            cur.execute(
                f"SELECT {self._CONTENT_COLUMNS} FROM content_pieces WHERE campaign_id = %s AND id = %s",
                (campaign_id, content_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def update_content_status(self, content_id: str, status: str, **kwargs: Any) -> dict:
        """Publish (optionally with an edited headline/body/embedding) or
        discard a draft. Only the fields actually passed get updated —
        approving an unedited draft just flips `status`."""
        fields = ["status = %(status)s"]
        params: dict[str, Any] = {"status": status, "id": content_id}
        if "headline" in kwargs:
            fields.append("headline = %(headline)s")
            params["headline"] = kwargs["headline"]
        if "body" in kwargs:
            fields.append("body = %(body)s")
            params["body"] = kwargs["body"]
        if "embedding" in kwargs and kwargs["embedding"] is not None:
            fields.append("embedding = %(embedding)s")
            params["embedding"] = vector_literal(kwargs["embedding"])

        def _do():
            with get_cursor(commit=True) as cur:
                cur.execute(
                    f"UPDATE content_pieces SET {', '.join(fields)} WHERE id = %(id)s "
                    f"RETURNING {self._CONTENT_COLUMNS}",
                    params,
                )
                return dict(cur.fetchone())

        return run_with_retry(_do)

    def update_content_image(
        self, content_id: str, image_data_url: str, image_source: str, image_prompt: str | None = None
    ) -> dict:
        def _do():
            with get_cursor(commit=True) as cur:
                cur.execute(
                    f"""
                    UPDATE content_pieces
                    SET image_data_url = %(image_data_url)s, image_source = %(image_source)s,
                        image_prompt = %(image_prompt)s
                    WHERE id = %(id)s
                    RETURNING {self._CONTENT_COLUMNS}
                    """,
                    {
                        "id": content_id,
                        "image_data_url": image_data_url,
                        "image_source": image_source,
                        "image_prompt": image_prompt,
                    },
                )
                return dict(cur.fetchone())

        return run_with_retry(_do)

    def search_similar_content(
        self, embedding: list[float], exclude_campaign_id: str | None, limit: int = 5
    ) -> list[dict]:
        """Cosine-distance nearest-neighbour search using the distributed
        vector index. This is the query that lets any campaign, in any
        region, recall precedent from every other campaign in the cluster - including, via the LATERAL join below, whether that precedent
        actually worked. Recalling a similar headline with no outcome
        attached is much weaker evidence than recalling one that's known to
        have converted well, so the caller needs both.

        Tries CockroachDB's Cloud Managed MCP Server first when configured - a genuine second read path for this memory query, not the direct
        driver alone - and falls back to the direct driver below on any
        failure (not configured, unreachable, no matching tool, whatever)."""
        vec = vector_literal(embedding)

        if mcp_client.is_configured():
            inline_sql = _similarity_sql_inline(vec, exclude_campaign_id, limit)
            mcp_rows = mcp_client.run_sql(inline_sql)
            if mcp_rows is not None:
                logger.info("search_similar_content served via CockroachDB Managed MCP Server (%d rows)", len(mcp_rows))
                return mcp_rows
            logger.info("MCP path unavailable for search_similar_content, falling back to direct driver")

        base_select = """
            SELECT cp.id, cp.campaign_id, c.name AS campaign_name, c.region,
                   cp.headline, cp.body, cp.channel, cp.cycle,
                   cp.embedding <-> %s AS distance,
                   pm.ctr, pm.conversions, pm.spend_usd, pm.impressions
            FROM content_pieces cp
            JOIN campaigns c ON c.id = cp.campaign_id
            LEFT JOIN LATERAL (
                SELECT ctr, conversions, spend_usd, impressions
                FROM performance_metrics
                WHERE content_id = cp.id
                ORDER BY recorded_at DESC
                LIMIT 1
            ) pm ON true
        """
        with get_cursor() as cur:
            if exclude_campaign_id:
                cur.execute(
                    base_select
                    + " WHERE cp.campaign_id != %s AND cp.embedding IS NOT NULL AND cp.status = 'published'"
                    " ORDER BY distance ASC LIMIT %s",
                    (vec, exclude_campaign_id, limit),
                )
            else:
                cur.execute(
                    base_select
                    + " WHERE cp.embedding IS NOT NULL AND cp.status = 'published' ORDER BY distance ASC LIMIT %s",
                    (vec, limit),
                )
            return [dict(r) for r in cur.fetchall()]

    def record_performance(self, **kwargs: Any) -> dict:
        def _do():
            with get_cursor(commit=True) as cur:
                cur.execute(
                    """
                    INSERT INTO performance_metrics
                        (content_id, campaign_id, cycle, impressions, clicks, conversions, spend_usd, ctr, conv_rate)
                    VALUES
                        (%(content_id)s, %(campaign_id)s, %(cycle)s, %(impressions)s, %(clicks)s,
                         %(conversions)s, %(spend_usd)s, %(ctr)s, %(conv_rate)s)
                    RETURNING *
                    """,
                    kwargs,
                )
                return dict(cur.fetchone())

        return run_with_retry(_do)

    def get_performance_history(self, campaign_id: str) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM performance_metrics WHERE campaign_id = %s ORDER BY cycle ASC",
                (campaign_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def log_decision(self, **kwargs: Any) -> dict:
        kwargs["detail"] = json.dumps(kwargs.get("detail") or {}, default=str)

        def _do():
            with get_cursor(commit=True) as cur:
                cur.execute(
                    """
                    INSERT INTO agent_decisions (campaign_id, cycle, phase, summary, detail)
                    VALUES (%(campaign_id)s, %(cycle)s, %(phase)s, %(summary)s, %(detail)s)
                    RETURNING *
                    """,
                    kwargs,
                )
                return dict(cur.fetchone())

        return run_with_retry(_do)

    def get_decisions(self, campaign_id: str) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM agent_decisions WHERE campaign_id = %s ORDER BY cycle ASC, created_at ASC",
                (campaign_id,),
            )
            rows = [dict(r) for r in cur.fetchall()]
        # psycopg2 auto-casts JSON but not always JSONB depending on driver
        # registration order - normalize defensively so callers never have
        # to care whether `detail` came back as a dict or a JSON string.
        for r in rows:
            if isinstance(r.get("detail"), str):
                r["detail"] = json.loads(r["detail"])
        return rows

    def add_trend_signal(self, **kwargs: Any) -> dict:
        def _do():
            with get_cursor(commit=True) as cur:
                cur.execute(
                    """
                    INSERT INTO trend_signals (campaign_id, topic, source, score)
                    VALUES (%(campaign_id)s, %(topic)s, %(source)s, %(score)s)
                    RETURNING *
                    """,
                    kwargs,
                )
                return dict(cur.fetchone())

        return run_with_retry(_do)

    def get_recent_trend_signals(self, campaign_id: str, limit: int = 5) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM trend_signals WHERE campaign_id = %s
                ORDER BY fetched_at DESC LIMIT %s
                """,
                (campaign_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]

    def reset_all(self) -> None:
        """Wipe every row in every table — the 'start fresh' control on the
        Settings page. No CASCADE on the FKs, so children go before parents."""

        def _do():
            with get_cursor(commit=True) as cur:
                for table in ("trend_signals", "agent_decisions", "performance_metrics", "content_pieces", "campaigns"):
                    cur.execute(f"DELETE FROM {table}")

        run_with_retry(_do)


# --------------------------------------------------------------------------
# In-memory implementation (offline / no-credentials mode)
# --------------------------------------------------------------------------

@dataclass
class _MemStore:
    campaigns: dict[str, dict] = field(default_factory=dict)
    content: dict[str, dict] = field(default_factory=dict)
    performance: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    trends: list[dict] = field(default_factory=list)


def _cosine_distance(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - (dot / (na * nb))


class InMemoryRepository:
    def __init__(self) -> None:
        self._store = _MemStore()

    def create_campaign(self, **kwargs: Any) -> dict:
        row = {"id": _uid(), "status": "active", "approval_mode": "autonomous", "created_at": _now(), **kwargs}
        self._store.campaigns[row["id"]] = row
        return row

    def get_campaigns(self) -> list[dict]:
        return sorted(self._store.campaigns.values(), key=lambda r: r["created_at"], reverse=True)

    def get_campaign(self, campaign_id: str) -> dict | None:
        return self._store.campaigns.get(campaign_id)

    def update_campaign_status(self, campaign_id: str, status: str) -> dict:
        row = self._store.campaigns[campaign_id]
        row["status"] = status
        return row

    def add_content_piece(self, **kwargs: Any) -> dict:
        row = {"id": _uid(), "created_at": _now(), "status": "published", **kwargs}
        self._store.content[row["id"]] = row
        return row

    def get_latest_content(self, campaign_id: str) -> dict | None:
        items = [
            c for c in self._store.content.values()
            if c["campaign_id"] == campaign_id and c.get("status") == "published"
        ]
        if not items:
            return None
        return max(items, key=lambda r: (r["cycle"], r["version"]))

    def get_pending_draft(self, campaign_id: str) -> dict | None:
        items = [
            c for c in self._store.content.values()
            if c["campaign_id"] == campaign_id and c.get("status") == "draft"
        ]
        if not items:
            return None
        return max(items, key=lambda r: (r["cycle"], r["version"]))

    def get_content(self, campaign_id: str, content_id: str) -> dict | None:
        row = self._store.content.get(content_id)
        if not row or row["campaign_id"] != campaign_id:
            return None
        return row

    def update_content_status(self, content_id: str, status: str, **kwargs: Any) -> dict:
        row = self._store.content[content_id]
        row["status"] = status
        if "headline" in kwargs:
            row["headline"] = kwargs["headline"]
        if "body" in kwargs:
            row["body"] = kwargs["body"]
        if "embedding" in kwargs and kwargs["embedding"] is not None:
            row["embedding"] = kwargs["embedding"]
        return row

    def update_content_image(
        self, content_id: str, image_data_url: str, image_source: str, image_prompt: str | None = None
    ) -> dict:
        row = self._store.content[content_id]
        row["image_data_url"] = image_data_url
        row["image_source"] = image_source
        row["image_prompt"] = image_prompt
        return row

    def _latest_outcome_for(self, content_id: str) -> dict | None:
        matches = [p for p in self._store.performance if p["content_id"] == content_id]
        if not matches:
            return None
        latest = max(matches, key=lambda p: p["recorded_at"])
        return {
            "ctr": latest.get("ctr"),
            "conversions": latest.get("conversions"),
            "spend_usd": latest.get("spend_usd"),
            "impressions": latest.get("impressions"),
        }

    def search_similar_content(
        self, embedding: list[float], exclude_campaign_id: str | None, limit: int = 5
    ) -> list[dict]:
        candidates = [
            c
            for c in self._store.content.values()
            if c.get("embedding") and c["campaign_id"] != exclude_campaign_id and c.get("status") == "published"
        ]
        scored = [
            {
                **c,
                "campaign_name": self._store.campaigns.get(c["campaign_id"], {}).get("name", "unknown"),
                "region": self._store.campaigns.get(c["campaign_id"], {}).get("region", "unknown"),
                "distance": _cosine_distance(embedding, c["embedding"]),
                **(self._latest_outcome_for(c["id"]) or {"ctr": None, "conversions": None, "spend_usd": None, "impressions": None}),
            }
            for c in candidates
        ]
        scored.sort(key=lambda r: r["distance"])
        return scored[:limit]

    def record_performance(self, **kwargs: Any) -> dict:
        row = {"id": _uid(), "recorded_at": _now(), **kwargs}
        self._store.performance.append(row)
        return row

    def get_performance_history(self, campaign_id: str) -> list[dict]:
        items = [p for p in self._store.performance if p["campaign_id"] == campaign_id]
        return sorted(items, key=lambda r: r["cycle"])

    def log_decision(self, **kwargs: Any) -> dict:
        row = {"id": _uid(), "created_at": _now(), **kwargs}
        self._store.decisions.append(row)
        return row

    def get_decisions(self, campaign_id: str) -> list[dict]:
        items = [d for d in self._store.decisions if d["campaign_id"] == campaign_id]
        return sorted(items, key=lambda r: (r["cycle"], r["created_at"]))

    def add_trend_signal(self, **kwargs: Any) -> dict:
        row = {"id": _uid(), "fetched_at": _now(), **kwargs}
        self._store.trends.append(row)
        return row

    def get_recent_trend_signals(self, campaign_id: str, limit: int = 5) -> list[dict]:
        items = [t for t in self._store.trends if t["campaign_id"] == campaign_id]
        items = sorted(items, key=lambda r: r["fetched_at"], reverse=True)
        return items[:limit]

    def reset_all(self) -> None:
        self._store = _MemStore()


@lru_cache
def get_repository() -> Repository:
    settings = get_settings()
    if settings.use_mock_db:
        return InMemoryRepository()
    return CockroachRepository()
