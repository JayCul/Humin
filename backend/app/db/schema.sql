-- Humin schema - CockroachDB
--
-- This is the agent's entire persistent memory: campaigns, the content it has
-- generated, how that content performed, the trend signals it saw, and the
-- reasoning trail behind every decision it made. Nothing here is ephemeral - -- everything the agent needs to pick up where it left off (or where a
-- *different* region's agent left off) lives in this cluster.
--
-- Run with: cockroach sql --url "$COCKROACHDB_URL" -f backend/app/db/schema.sql
--
-- If you already ran this against a live cluster before budget_usd existed:
--   ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS budget_usd DECIMAL(10, 2);
-- ...or before approval_mode / content status existed:
--   ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS approval_mode STRING NOT NULL DEFAULT 'autonomous';
--   ALTER TABLE content_pieces ADD COLUMN IF NOT EXISTS status STRING NOT NULL DEFAULT 'published';
-- ...or before ad creative images existed:
--   ALTER TABLE content_pieces ADD COLUMN IF NOT EXISTS image_data_url STRING;
--   ALTER TABLE content_pieces ADD COLUMN IF NOT EXISTS image_source STRING;
--   ALTER TABLE content_pieces ADD COLUMN IF NOT EXISTS image_prompt STRING;

CREATE TABLE IF NOT EXISTS campaigns (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              STRING NOT NULL,
    product           STRING NOT NULL,
    audience_segment  STRING NOT NULL,
    goal              STRING NOT NULL,          -- 'awareness' | 'conversion' | 'retention'
    tone              STRING NOT NULL DEFAULT 'confident, plain-spoken',
    status            STRING NOT NULL DEFAULT 'active',
    region            STRING NOT NULL DEFAULT 'us-east',  -- home region; demonstrates multi-region shape
    budget_usd        DECIMAL(10, 2),                     -- NULL = unlimited. Enforced in orchestrator._apply_budget_guardrail
    approval_mode     STRING NOT NULL DEFAULT 'autonomous', -- 'autonomous' | 'review' — see content_pieces.status
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every piece of generated content, versioned. `embedding` is what makes this
-- table Humin's long-term memory rather than just a content log: any future
-- cycle, for any campaign, in any region, can ask "what has worked before
-- for something like this?" via vector search across ALL rows here.
CREATE TABLE IF NOT EXISTS content_pieces (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id              UUID NOT NULL REFERENCES campaigns(id),
    cycle                    INT NOT NULL,
    version                  INT NOT NULL DEFAULT 1,
    channel                  STRING NOT NULL,   -- 'email' | 'social' | 'search_ad' | 'display'
    headline                 STRING NOT NULL,
    body                     STRING NOT NULL,
    embedding                VECTOR(1024),      -- Titan Embed Text v2 dimensionality
    -- The actual ad creative: a data: URL (image/png or image/jpeg) so it
    -- renders directly in an <img> tag with no extra storage/CORS plumbing.
    -- Deliberately NOT part of `embedding` (still text-only) or ever echoed
    -- into agent_decisions.detail - kept off the audit trail so a Lambda
    -- Function URL response for a long-running campaign's decision history
    -- never approaches the 6MB payload ceiling; fetched per-content-piece
    -- instead, one image at a time. NULL until Act generates or a reviewer
    -- uploads one.
    image_data_url           STRING,
    image_source             STRING,   -- 'generated' | 'uploaded'
    image_prompt             STRING,   -- Huginn's visual direction, or an uploader's caption
    generated_by_decision_id UUID,
    -- 'draft' = awaiting human review (campaigns.approval_mode = 'review'),
    -- excluded from vector recall and get_latest_content until approved.
    -- 'discarded' = rejected by a reviewer; kept for audit, never recalled.
    -- 'published' = live — the only status the agent's memory actually uses.
    status                   STRING NOT NULL DEFAULT 'published',
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Native distributed vector index - this is the "Distributed Vector
-- Indexing" CockroachDB tool the hackathon asks teams to integrate.
CREATE VECTOR INDEX IF NOT EXISTS content_embedding_idx
    ON content_pieces (embedding);

CREATE TABLE IF NOT EXISTS performance_metrics (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id    UUID NOT NULL REFERENCES content_pieces(id),
    campaign_id   UUID NOT NULL REFERENCES campaigns(id),
    cycle         INT NOT NULL,
    impressions   INT NOT NULL,
    clicks        INT NOT NULL,
    conversions   INT NOT NULL,
    spend_usd     DECIMAL(10, 2) NOT NULL,
    ctr           DECIMAL(7, 5),
    conv_rate     DECIMAL(7, 5),
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The agent's reasoning trail: one row per phase, per cycle. This is what
-- lets a human (or the agent itself, next cycle) reconstruct *why* a
-- decision was made, not just what changed.
CREATE TABLE IF NOT EXISTS agent_decisions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id  UUID NOT NULL REFERENCES campaigns(id),
    cycle        INT NOT NULL,
    phase        STRING NOT NULL,   -- 'perceive' | 'remember' | 'think' | 'act' | 'learn'
    summary      STRING NOT NULL,
    detail       JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Real, read-only external grounding signal (e.g. Google Trends) that feeds
-- the "perceive" phase alongside internal performance data.
CREATE TABLE IF NOT EXISTS trend_signals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID REFERENCES campaigns(id),
    topic       STRING NOT NULL,
    source      STRING NOT NULL,
    score       DECIMAL(7, 4),
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_content_campaign ON content_pieces (campaign_id, cycle DESC);
CREATE INDEX IF NOT EXISTS idx_perf_campaign ON performance_metrics (campaign_id, cycle DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_campaign ON agent_decisions (campaign_id, cycle DESC);
CREATE INDEX IF NOT EXISTS idx_trends_campaign ON trend_signals (campaign_id, fetched_at DESC);
