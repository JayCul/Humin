# Humin frontend

Next.js (App Router) dashboard for the Humin agent.

## Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local   # points at the backend, defaults to localhost:8000
npm run dev
```

Open `http://localhost:3000`. Make sure the backend (`../backend`) is running
first - the dashboard is a pure client that reads/writes through its REST API.

## Pages

- `/` - campaign list + create-campaign form
- `/campaign/[id]` - one campaign's live dashboard:
  - performance chart (CTR / conversions across cycles)
  - full agent reasoning trail (Perceive → Remember → Think → Act → Learn)
  - latest generated content + the rationale behind it
  - "recalled from memory" panel showing what the vector search in
    CockroachDB surfaced from *other* campaigns/regions
  - a **Run next cycle** button that triggers `POST /campaigns/{id}/run-cycle`
    live, so the whole loop can be driven from the UI during a demo
