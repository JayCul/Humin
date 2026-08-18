# Humin backend

FastAPI service running the agent loop (`app/agent/orchestrator.py`):
**Perceive → Remember → Think → Act → Learn**.

## Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Leave `USE_MOCK_LLM=true` and `USE_MOCK_DB=true` (the defaults) to run
entirely offline - deterministic mock content generation, mock embeddings,
and an in-memory repository standing in for CockroachDB. This is enough to
exercise and demo the full agent loop.

To run against real infrastructure:

1. Provision a CockroachDB Cloud cluster, set `COCKROACHDB_URL` in `.env`,
   apply the schema:
   ```bash
   cockroach sql --url "$COCKROACHDB_URL" -f app/db/schema.sql
   ```
   Set `USE_MOCK_DB=false`.
2. Ensure AWS credentials with `bedrock:InvokeModel` are available (env vars,
   shared profile, or an execution role if deployed to Lambda), request model
   access for Claude 3.5 Sonnet + Titan Embed Text v2 in the Bedrock console,
   set `USE_MOCK_LLM=false`.
3. Optionally set `TRENDS_PROVIDER=google_trends` for a live trend signal
   instead of the mock topic list.

## Run

```bash
python scripts/seed.py          # creates 3 demo campaigns + a few cycles of history
uvicorn app.main:app --reload --port 8000
```

API docs at `http://localhost:8000/docs`.

## Key endpoints

| Method | Path                                    | What it does                                   |
|--------|------------------------------------------|-------------------------------------------------|
| POST   | `/api/campaigns`                         | Create a campaign                                |
| GET    | `/api/campaigns`                         | List campaigns                                   |
| GET    | `/api/campaigns/{id}`                    | Campaign detail                                  |
| POST   | `/api/campaigns/{id}/run-cycle`          | Run one Perceive→Remember→Think→Act→Learn cycle (409 if the campaign isn't active) |
| POST   | `/api/campaigns/{id}/pause`              | Manually pause a campaign                        |
| POST   | `/api/campaigns/{id}/resume`             | Resume a paused campaign                         |
| GET    | `/api/campaigns/{id}/performance`        | Performance history (for charting)               |
| GET    | `/api/campaigns/{id}/decisions`          | Full agent reasoning trail                       |
| GET    | `/api/campaigns/{id}/trends`             | Recent trend signals seen                        |

## Decisions the agent can make

Each cycle, the Think phase picks one of five moves - not a binary
keep/pivot - and a code-level guardrail (`orchestrator._apply_guardrails`)
downgrades `pivot_*`/`kill` back to `tweak` whenever the evidence behind
them is too thin, regardless of what the model itself claims:

- `keep` - current angle is working, ship a close variant to keep testing it
- `tweak` - small copy/framing change, same angle and channel
- `pivot_angle` - change the core message/positioning, same channel
- `pivot_channel` - same message, different channel
- `kill` - recommend stopping this direction entirely; the orchestrator
  actually pauses the campaign (`status` → `paused`) rather than just
  labeling the decision - resume it via `POST /campaigns/{id}/resume`

## Module map

- `app/db/` - CockroachDB schema + repository (real + in-memory implementations)
- `app/agent/bedrock_client.py` - Huginn: strategy reasoning + embeddings via Bedrock
- `app/agent/orchestrator.py` - the 5-phase loop that ties everything together
- `app/simulator/ad_platform_sim.py` - synthetic performance generator
- `app/signals/trends_client.py` - real read-only trend signal (Google Trends) or mock
- `app/api/routes.py` - HTTP surface for the frontend
