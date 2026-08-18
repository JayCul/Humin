"""CockroachDB Cloud Managed MCP Server client.

A real MCP (Model Context Protocol) client - not a config placeholder. When
`COCKROACHDB_MCP_URL` is set, this connects to CockroachDB Cloud's managed
MCP server over streamable-HTTP, discovers whatever tools it actually
exposes, and can route a memory read through one of them instead of the
direct psycopg2 driver.

Deliberately adaptive rather than hardcoded to one assumed tool name or
argument shape: CockroachDB's exact MCP tool surface isn't something we
had a live endpoint to verify against while building this, so at connect
time we discover the real tool list, pattern-match for a SQL-execution-
shaped tool by name/description, and read its own JSON schema to figure out
which argument holds the query text - rather than guessing wrong and
failing silently forever. If nothing matching is found, or the endpoint
isn't configured or reachable, every function here returns `None`/`[]`
instead of raising - MCP is an additional path alongside the direct driver,
never a single point of failure for the agent loop. The first real call
against a live endpoint logs exactly which tools were discovered, so it's
immediately obvious whether the guess was right.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from app.config import get_settings

logger = logging.getLogger("humin.mcp")

_SQL_HINT = re.compile(r"(sql|query|execute|statement)", re.IGNORECASE)
_QUERY_PARAM_CANDIDATES = ("sql", "query", "statement", "command")


def is_configured() -> bool:
    return bool(get_settings().cockroachdb_mcp_url)


def _auth_headers() -> dict[str, str]:
    key = get_settings().cockroachdb_mcp_api_key
    return {"Authorization": f"Bearer {key}"} if key else {}


async def _open_session():
    """Yields an initialized MCP ClientSession against the configured
    endpoint. Import mcp/httpx2 lazily so the rest of the app works even in
    environments where these optional deps aren't installed.

    Note: the `mcp` package (v2.x) depends on `httpx2` - a separate PyPI
    package, not the more commonly known `httpx` - for its HTTP transport.
    `streamable_http_client`'s `http_client` argument specifically expects
    an `httpx2.AsyncClient`."""
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    s = get_settings()
    http_client = httpx2.AsyncClient(headers=_auth_headers())
    async with streamable_http_client(s.cockroachdb_mcp_url, http_client=http_client) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def _list_tools_async() -> list[dict[str, Any]]:
    async for session in _open_session():
        result = await session.list_tools()
        tools = [
            {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
            for t in result.tools
        ]
        logger.info(
            "CockroachDB Managed MCP Server: connected, exposes %d tool(s): %s",
            len(tools),
            [t["name"] for t in tools],
        )
        return tools
    return []


def list_tools() -> list[dict[str, Any]]:
    """Sync wrapper - the rest of Humin's backend is synchronous (psycopg2),
    so this is the boundary where we drop into asyncio for the MCP call.
    Used by the Settings page to show what's actually live, and safe to
    call even when nothing is configured (returns [])."""
    if not is_configured():
        return []
    try:
        return asyncio.run(_list_tools_async())
    except Exception as exc:  # unreachable endpoint, auth failure, protocol mismatch, etc.
        logger.warning("Could not reach CockroachDB Managed MCP Server: %s", exc)
        return []


def _pick_query_param(input_schema: dict[str, Any] | None) -> str | None:
    """The exact argument name a SQL-execution tool expects isn't something
    to hardcode - inspect the tool's own JSON schema for a familiar name
    first, then fall back to 'the one string parameter' if there's exactly
    one candidate."""
    if not input_schema:
        return None
    props = input_schema.get("properties", {})
    for candidate in _QUERY_PARAM_CANDIDATES:
        if candidate in props:
            return candidate
    string_props = [k for k, v in props.items() if isinstance(v, dict) and v.get("type") == "string"]
    return string_props[0] if len(string_props) == 1 else None


def _parse_tool_result(result: Any) -> list[dict[str, Any]]:
    """MCP tool results come back as content blocks; a SQL tool typically
    returns rows as structured JSON (preferred) or as JSON-encoded text."""
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if structured:
        return structured if isinstance(structured, list) else structured.get("rows", [structured])

    rows: list[dict[str, Any]] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        rows.extend(parsed if isinstance(parsed, list) else [parsed])
    return rows


async def _run_sql_async(sql: str) -> list[dict[str, Any]] | None:
    async for session in _open_session():
        tools_result = await session.list_tools()
        tools = list(tools_result.tools)
        sql_tool = next((t for t in tools if _SQL_HINT.search(f"{t.name} {t.description or ''}")), None)
        if sql_tool is None:
            logger.warning(
                "No SQL-shaped tool discovered on the MCP server (available: %s)",
                [t.name for t in tools],
            )
            return None
        param = _pick_query_param(sql_tool.input_schema)
        if param is None:
            logger.warning("Could not determine the query argument for MCP tool '%s'", sql_tool.name)
            return None
        logger.info("Routing query through MCP tool '%s' (argument '%s')", sql_tool.name, param)
        result = await session.call_tool(sql_tool.name, {param: sql})
        return _parse_tool_result(result)
    return None


def run_sql(sql: str) -> list[dict[str, Any]] | None:
    """Execute a read-only query through the MCP server's SQL-shaped tool,
    if one is discoverable. Returns None (never raises) when MCP isn't
    configured, unreachable, or doesn't expose a usable tool - callers are
    expected to fall back to the direct driver in that case."""
    if not is_configured():
        return None
    try:
        return asyncio.run(_run_sql_async(sql))
    except Exception as exc:
        logger.warning("MCP query failed (%s) - falling back to the direct driver", exc)
        return None
