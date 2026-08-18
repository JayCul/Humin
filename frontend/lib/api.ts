const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api";

export type Campaign = {
  id: string;
  name: string;
  product: string;
  audience_segment: string;
  goal: string;
  tone: string;
  status: string;
  region: string;
  budget_usd: number | null;
  approval_mode: "autonomous" | "review";
  created_at: string;
};

export type ContentPiece = {
  id: string;
  campaign_id: string;
  cycle: number;
  version: number;
  channel: string;
  headline: string;
  body: string;
  status: "draft" | "published" | "discarded";
  image_data_url: string | null;
  image_source: "generated" | "uploaded" | null;
  image_prompt: string | null;
  created_at: string;
};

export type SchedulerStatus = {
  enabled: boolean;
  interval_seconds: number;
  last_run_at: string | null;
  last_run_summary: { ran: number; errors: number } | null;
  next_run_at: string | null;
};

export type PerformancePoint = {
  id: string;
  campaign_id: string;
  cycle: number;
  impressions: number;
  clicks: number;
  conversions: number;
  spend_usd: number;
  ctr: number;
  conv_rate: number;
  recorded_at: string;
};

export type Decision = {
  id: string;
  campaign_id: string;
  cycle: number;
  phase: "perceive" | "remember" | "think" | "act" | "learn";
  summary: string;
  detail: Record<string, unknown>;
  created_at: string;
};

export type TrendSignal = {
  id: string;
  campaign_id: string;
  topic: string;
  source: string;
  score: number;
  fetched_at: string;
};

export type AgentDecisionType = "keep" | "tweak" | "pivot_angle" | "pivot_channel" | "kill";

export type RecalledMemoryItem = {
  campaign_name: string;
  region: string;
  headline: string;
  channel?: string;
  similarity: number;
  outcome: { ctr: number; conversions: number; spend_usd: number | null } | null;
};

export type Strategy = {
  decision: AgentDecisionType;
  performance_assessment: string;
  memory_assessment: string;
  trend_assessment: string;
  rationale: string;
  headline: string;
  body: string;
  confidence: number;
  confidence_breakdown?: {
    model_self_reported: number;
    evidence_strength: number;
    final: number;
  };
  guardrail_notes?: string[];
  guardrail_categories?: ("plateau" | "evidence" | "budget")[];
};

export type SystemStatus = {
  cockroachdb: { mode: "live" | "mock"; url_configured: boolean; mcp_configured: boolean; mcp_tools: string[] };
  bedrock: {
    mode: "live" | "mock";
    text_model_id: string;
    embedding_model_id: string;
    embedding_dimensions: number;
    aws_region: string;
  };
  trends: { provider: string };
  scheduler: {
    default_interval_seconds: number;
    enabled: boolean;
    interval_seconds: number;
    last_run_at: string | null;
    last_run_summary: { ran: number; errors: number } | null;
    next_run_at: string | null;
  };
  environment: string;
};

export type CycleResult = {
  campaign_id: string;
  cycle: number;
  perceive: Record<string, unknown>;
  remember: RecalledMemoryItem[];
  think: Strategy;
  act: { content: Record<string, unknown> | null; channel: string | null; paused?: boolean } | null;
  learn: PerformancePoint | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listCampaigns: () => request<Campaign[]>("/campaigns"),
  getCampaign: (id: string) => request<Campaign>(`/campaigns/${id}`),
  createCampaign: (payload: Omit<Campaign, "id" | "status" | "created_at">) =>
    request<Campaign>("/campaigns", { method: "POST", body: JSON.stringify(payload) }),
  runCycle: (id: string) => request<CycleResult>(`/campaigns/${id}/run-cycle`, { method: "POST" }),
  pauseCampaign: (id: string) => request<Campaign>(`/campaigns/${id}/pause`, { method: "POST" }),
  resumeCampaign: (id: string) => request<Campaign>(`/campaigns/${id}/resume`, { method: "POST" }),
  getPerformance: (id: string) => request<PerformancePoint[]>(`/campaigns/${id}/performance`),
  getDecisions: (id: string) => request<Decision[]>(`/campaigns/${id}/decisions`),
  getTrends: (id: string) => request<TrendSignal[]>(`/campaigns/${id}/trends`),
  getSchedulerStatus: () => request<SchedulerStatus>("/scheduler/status"),
  startScheduler: (intervalSeconds?: number) =>
    request<SchedulerStatus>("/scheduler/start", {
      method: "POST",
      body: JSON.stringify({ interval_seconds: intervalSeconds }),
    }),
  stopScheduler: () => request<SchedulerStatus>("/scheduler/stop", { method: "POST" }),
  getSystemStatus: () => request<SystemStatus>("/system/status"),
  resetAllData: () => request<{ status: string; campaigns: Campaign[] }>("/system/reset", { method: "POST" }),
  seedDemoData: () =>
    request<{ status: string; campaigns: Campaign[]; log: string[] }>("/system/seed-demo", { method: "POST" }),
  getPendingDraft: (id: string) => request<ContentPiece | null>(`/campaigns/${id}/pending-draft`),
  approveDraft: (id: string, edits?: { headline?: string; body?: string }) =>
    request<CycleResult>(`/campaigns/${id}/pending-draft/approve`, {
      method: "POST",
      body: JSON.stringify(edits ?? {}),
    }),
  discardDraft: (id: string) =>
    request<{ campaign_id: string; cycle: number; status: string }>(`/campaigns/${id}/pending-draft/discard`, {
      method: "POST",
    }),
  regenerateDraft: (id: string, feedback?: string) =>
    request<CycleResult>(`/campaigns/${id}/pending-draft/regenerate`, {
      method: "POST",
      body: JSON.stringify({ feedback }),
    }),
  getContent: (campaignId: string, contentId: string) =>
    request<ContentPiece>(`/campaigns/${campaignId}/content/${contentId}`),
  uploadContentImage: async (campaignId: string, contentId: string, file: File): Promise<ContentPiece> => {
    const form = new FormData();
    form.append("file", file);
    // No Content-Type header here on purpose - the browser sets
    // multipart/form-data with the correct boundary itself; setting it
    // manually (as `request()` does for JSON) breaks the boundary.
    const res = await fetch(`${API_BASE}/campaigns/${campaignId}/content/${contentId}/image`, {
      method: "POST",
      body: form,
      cache: "no-store",
    });
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new Error(`${res.status} ${res.statusText}: ${text}`);
    }
    return res.json() as Promise<ContentPiece>;
  },
};
