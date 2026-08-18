# Humin 🐦‍⬛🐦‍⬛

**Humin** (originates from _Huginn_ & _Muninn_ - Odin's ravens, Thought and Memory) is an
autonomous ad manager built for the **CockroachDB × AWS "Agentic
Memory" Hackathon**.

Every morning, Odin sent his two ravens out over the world: **Huginn** to think,
**Muninn** to remember what he saw. Humin runs the same loop for ad
campaigns - a small agent that goes out, reasons about what's working, and
never forgets what it learned, no matter how many campaigns or regions it's
watching at once.

> **Think → Remember → Learn → Adapt**, running on a memory layer that survives
> node failures and stays globally consistent.

## What it does

Humin plans, generates, and iterates on ad campaign copy autonomously - with an
optional human-in-the-loop review step before anything publishes:

1. **Perceive** - pulls the latest performance metrics for a campaign (CTR,
   conversions, spend) plus a live external trend signal.
2. **Remember** _(Muninn)_ - embeds the current campaign context and runs a
   vector similarity search across **every past campaign, in every region**,
   stored in CockroachDB, to recall which ads actually worked in similar
   situations.
3. **Think** _(Huginn)_ - hands performance data + recalled precedent + trend
   signal to an LLM (Amazon Bedrock) to decide: keep the strategy, or pivot,
   and drafts new ad copy accordingly.
4. **Act** - writes the new ad variant and a full rationale/decision log back
   into CockroachDB - this cycle's outcome becomes next cycle's memory. A
   campaign can be set to require human approval first: the draft waits for a
   reviewer to approve (with or without edits), send it back with feedback
   for a redraft, or discard it, before it ever publishes.
5. **Learn** - a synthetic ad-platform simulator (grounded by the real trend
   signal) produces performance results for the published ad, closing the loop.

Nothing here calls a real ad platform or spends real money - the focus is the
autonomous reasoning + memory loop, which is what the hackathon judges.

## Why CockroachDB is load-bearing, not decorative

- **Distributed Vector Indexing** - `content_pieces.embedding` is a native
  `VECTOR` column with a vector index. Similarity search spans _all_
  campaigns/regions in one query - the "global memory" a single-region
  Postgres instance can't offer as naturally.
- **Cloud Managed MCP Server** - the agent talks to the cluster through
  CockroachDB's managed MCP server rather than a hand-rolled driver-only
  integration, so cluster access is itself an agent-native tool call.
- Every campaign row carries a `region` - the schema is deliberately
  multi-region shaped so the demo can show the memory layer surviving a
  simulated node/region failure without losing agent state.

See [docs/COCKROACHDB_AWS_USAGE.md](docs/COCKROACHDB_AWS_USAGE.md) for the
full tool-by-tool mapping required by the submission, and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the diagram + data flow.

## Repo layout

```
Humin/
├── backend/     FastAPI service - the agent loop, CockroachDB access, Bedrock calls
├── frontend/    Next.js dashboard - campaigns, live agent trace, memory explorer
├── infra/       AWS Lambda handler for scheduled/triggered agent runs
└── docs/        Architecture + hackathon-required tool documentation
```

## Quickstart

See [backend/README.md](backend/README.md) and
[frontend/README.md](frontend/README.md) for setup. Short version:

```bash
# Backend
cd backend
cp .env.example .env   # fill in CockroachDB + AWS Bedrock credentials
pip install -r requirements.txt
python scripts/seed.py     # creates demo campaigns + a few history cycles
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

Without any credentials filled in, the backend runs in **mock mode**
(`USE_MOCK_LLM=true`, in-memory fallback) so the loop is demoable offline - flip the env vars once your CockroachDB Cloud cluster and Bedrock access are
live.

## License

MIT - see [LICENSE](LICENSE).
