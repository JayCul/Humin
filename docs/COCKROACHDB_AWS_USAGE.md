# CockroachDB & AWS tool usage

Required by the hackathon submission: at least **2 CockroachDB tools** and
**1 AWS service**. Humin uses:

## CockroachDB (2 of 4 required tools)

### 1. Distributed Vector Indexing
- **Where:** `backend/app/db/schema.sql` - `content_pieces.embedding VECTOR(1024)`
  with `CREATE VECTOR INDEX content_embedding_idx ON content_pieces (embedding)`.
- **Where used:** `CockroachRepository.search_similar_content()` in
  [`backend/app/db/repository.py`](../backend/app/db/repository.py), called
  from the **Remember** phase of [`orchestrator.py`](../backend/app/agent/orchestrator.py).
- **Why it matters here:** every campaign's new content is embedded and
  stored; every cycle's Remember phase runs a `<->` cosine-distance
  nearest-neighbour search across the *entire* cluster - all campaigns, all
  regions - to recall precedent before deciding on new strategy. This is the
  mechanism that makes Humin's memory more than a per-campaign log.

### 2. Cloud Managed MCP Server
- **Where:** [`backend/app/db/mcp_client.py`](../backend/app/db/mcp_client.py) - a real MCP client (via the official `mcp` Python SDK, streamable-HTTP
  transport), not a config placeholder. `CockroachRepository.search_similar_content()`
  in [`repository.py`](../backend/app/db/repository.py) tries the MCP path
  first whenever `COCKROACHDB_MCP_URL` is set, and falls back to the direct
  driver on any failure - a genuine second read path for the Remember phase,
  never a single point of failure for the agent loop.
- **Why:** the agent's memory reads become tool calls the same way its
  Bedrock calls are, rather than a bespoke driver-only integration.
- **Adaptive by design:** the client discovers whatever tools the managed
  MCP server actually exposes at connect time (`list_tools()`) and
  pattern-matches for a SQL-execution-shaped one, reading *that tool's own*
  JSON schema to figure out its query argument name - rather than hardcoding
  an assumed tool name/shape we hadn't verified against a live endpoint.
- **Status:** implemented and exercised against a live CockroachDB Cloud
  cluster for the direct-driver path (see `docs/DEPLOYMENT.md`); the MCP
  path itself activates the moment `COCKROACHDB_MCP_URL` /
  `COCKROACHDB_MCP_API_KEY` are set - the Settings page shows exactly which
  tools it discovered once connected.

### (Not used, in scope for future work)
- ccloud CLI - cluster provisioning/ops, not part of the runtime agent loop.
- Agent Skills Repo - candidate for packaging Humin's own Perceive/Remember/
  Think/Act/Learn steps as reusable skills.

## AWS (1 of N required services)

### Amazon Bedrock
- **Where:** [`backend/app/agent/bedrock_client.py`](../backend/app/agent/bedrock_client.py).
- **Models:** `us.anthropic.claude-haiku-4-5-20251001-v1:0` for the **Think**
  phase (strategy decision + content generation), `amazon.titan-embed-text-v2:0`
  for embeddings used in both **Remember** (query embedding) and **Act**
  (storing new content's embedding).
- **Fallback:** `USE_MOCK_LLM=true` runs deterministic mock logic with the
  same interface, so the loop is demoable without live AWS access; flip to
  `false` once Bedrock model access is granted in the target region.

### AWS Lambda
- **Where:** [`infra/lambda/handler.py`](../infra/lambda/handler.py).
- **Role:** scheduled/event-driven entry point that runs one cycle per
  active campaign - the same `run_cycle()` (via `orchestrator.run_all_active_campaigns()`)
  used by the FastAPI backend, so local dev, the live demo API, and the
  production scheduled path all share one code path.

### Amazon EventBridge
- **Where:** deployment steps in [`infra/README.md`](../infra/README.md)
  (`aws events put-rule` / `put-targets`).
- **Role:** puts the Lambda above on a recurring schedule (e.g. `rate(1 hour)`)
  so campaigns keep adapting on their own in production, without a human or
  the dashboard driving each cycle.
- **Demo-path equivalent:** [`backend/app/scheduler.py`](../backend/app/scheduler.py) - an in-process scheduler toggled from the dashboard ("Enable autonomous
  mode"), calling the identical `run_all_active_campaigns()` function on an
  interval, so the loop's autonomy is demonstrable live without requiring a
  deployed AWS stack in front of judges.

## Setup checklist (for judges reproducing the demo locally)

1. `cockroach sql --url "$COCKROACHDB_URL" -f backend/app/db/schema.sql`
2. Request Bedrock model access for Claude 3.5 Sonnet + Titan Embed Text v2
   in the target AWS region.
3. Set `USE_MOCK_DB=false`, `USE_MOCK_LLM=false` in `backend/.env`.
4. `python scripts/seed.py` then `uvicorn app.main:app --reload`.
5. `cd frontend && npm run dev`.

For the deployed version (Lambda + EventBridge + a public URL), see
[`docs/DEPLOYMENT.md`](DEPLOYMENT.md).
