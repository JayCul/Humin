"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type Campaign, type Decision, type RecalledMemoryItem, type Strategy } from "@/lib/api";

type DecisionBucket = "keep" | "tweak" | "pivot" | "kill";

const BUCKET_META: Record<DecisionBucket, { label: string; color: string }> = {
  keep: { label: "Keep", color: "var(--status-good)" },
  tweak: { label: "Tweak", color: "var(--status-warning)" },
  pivot: { label: "Pivot", color: "var(--status-serious)" },
  kill: { label: "Kill", color: "var(--status-critical)" },
};

function bucketOf(decision: string): DecisionBucket {
  if (decision === "pivot_angle" || decision === "pivot_channel") return "pivot";
  if (decision === "kill") return "kill";
  if (decision === "tweak") return "tweak";
  return "keep";
}

export default function InsightsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [decisionsByCampaign, setDecisionsByCampaign] = useState<Record<string, Decision[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"chart" | "table">("chart");

  useEffect(() => {
    (async () => {
      try {
        const list = await api.listCampaigns();
        setCampaigns(list);
        const entries = await Promise.all(
          list.map(async (c) => [c.id, await api.getDecisions(c.id).catch(() => [])] as const)
        );
        setDecisionsByCampaign(Object.fromEntries(entries));
      } catch (e) {
        setError((e as Error).message);
      }
    })();
  }, []);

  if (error) {
    return (
      <div className="card">
        <p style={{ color: "var(--rose)" }}>{error}</p>
      </div>
    );
  }

  if (campaigns === null) {
    return <div className="empty-state">Loading…</div>;
  }

  const allDecisions = Object.values(decisionsByCampaign).flat();
  const thinkDecisions = allDecisions.filter((d) => d.phase === "think");
  const rememberDecisions = allDecisions.filter((d) => d.phase === "remember");

  const bucketCounts: Record<DecisionBucket, number> = { keep: 0, tweak: 0, pivot: 0, kill: 0 };
  const rawCounts: Record<string, number> = {};
  const guardrailCounts = { plateau: 0, evidence: 0, budget: 0 };
  const confidenceByCycle = new Map<number, { sum: number; count: number }>();

  for (const d of thinkDecisions) {
    const s = d.detail as unknown as Strategy;
    if (!s?.decision) continue;
    bucketCounts[bucketOf(s.decision)] += 1;
    rawCounts[s.decision] = (rawCounts[s.decision] ?? 0) + 1;
    for (const cat of s.guardrail_categories ?? []) {
      guardrailCounts[cat] += 1;
    }
    if (typeof s.confidence === "number") {
      const bucket = confidenceByCycle.get(d.cycle) ?? { sum: 0, count: 0 };
      bucket.sum += s.confidence;
      bucket.count += 1;
      confidenceByCycle.set(d.cycle, bucket);
    }
  }

  let memoryInformedCount = 0;
  for (const d of rememberDecisions) {
    const recalled = (d.detail?.recalled as RecalledMemoryItem[] | undefined) ?? [];
    if (recalled.some((r) => r.outcome != null)) memoryInformedCount += 1;
  }

  const totalThink = thinkDecisions.length;
  const totalGuardrailFires = guardrailCounts.plateau + guardrailCounts.evidence + guardrailCounts.budget;
  const memoryInformedPct = rememberDecisions.length > 0 ? (memoryInformedCount / rememberDecisions.length) * 100 : 0;

  const barData = (Object.keys(BUCKET_META) as DecisionBucket[]).map((b) => ({
    bucket: BUCKET_META[b].label,
    count: bucketCounts[b],
    color: BUCKET_META[b].color,
    key: b,
  }));

  const confidenceData = Array.from(confidenceByCycle.entries())
    .sort(([a], [b]) => a - b)
    .map(([cycle, { sum, count }]) => ({ cycle: `C${cycle}`, avgConfidence: Math.round((sum / count) * 100) }));

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1>Insights</h1>
        <p>What the agent actually did, in aggregate, across every ad campaign - not one cherry-picked run.</p>
      </div>

      <div className="kpi-row">
        <div className="card kpi-card">
          <span className="icon-badge icon-badge-teal">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 20V10M12 20V4M20 20v-7" />
            </svg>
          </span>
          <div>
            <div className="kpi-value">{totalThink}</div>
            <div className="kpi-label">Decisions made</div>
          </div>
        </div>
        <div className="card kpi-card">
          <span className="icon-badge icon-badge-gold">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M4 12c1.5-4 5-6.5 8-6.5s6.5 2.5 8 6.5c-1.5 4-5 6.5-8 6.5S5.5 16 4 12z" />
            </svg>
          </span>
          <div>
            <div className="kpi-value">{memoryInformedPct.toFixed(0)}%</div>
            <div className="kpi-label">Memory-informed recalls</div>
          </div>
        </div>
        <div className="card kpi-card">
          <span className="icon-badge icon-badge-rose">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 9v4M12 17h.01" />
              <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            </svg>
          </span>
          <div>
            <div className="kpi-value">{totalGuardrailFires}</div>
            <div className="kpi-label">Guardrail interventions</div>
          </div>
        </div>
        <div className="card kpi-card">
          <span className="icon-badge icon-badge-green">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 20V10M18 20V4M6 20v-4" />
            </svg>
          </span>
          <div>
            <div className="kpi-value">{campaigns.length}</div>
            <div className="kpi-label">Campaigns tracked</div>
          </div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 20 }}>
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div className="section-title" style={{ marginBottom: 0 }}>
              Decision distribution
            </div>
            <button className="chart-view-toggle" onClick={() => setView(view === "chart" ? "table" : "chart")}>
              {view === "chart" ? "View as table" : "View as chart"}
            </button>
          </div>
          <p style={{ fontSize: 12, marginTop: 8 }}>
            Keep = working, stay the course. Tweak = small edit. Pivot = angle or channel change. Kill = agent
            recommended stopping. Color encodes severity of the move, not identity.
          </p>
          {view === "chart" ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={barData} margin={{ top: 8, right: 16, left: -16, bottom: 0 }}>
                <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                <XAxis dataKey="bucket" stroke="var(--chart-ink-muted)" fontSize={12} tickLine={false} axisLine={{ stroke: "var(--chart-axis)" }} />
                <YAxis stroke="var(--chart-ink-muted)" fontSize={12} tickLine={false} axisLine={false} width={32} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: "var(--bg-elevated)", border: "1px solid var(--panel-border)", borderRadius: 8, fontSize: 12 }}
                  formatter={(v: number) => [v, "Decisions"]}
                />
                <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={48} isAnimationActive={false}>
                  {barData.map((d) => (
                    <Cell key={d.key} fill={d.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Decision</th>
                    <th>Count</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(rawCounts).map(([k, v]) => (
                    <tr key={k}>
                      <td>{k.replace("_", " ")}</td>
                      <td>{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card">
          <div className="section-title">Fleet-wide confidence trend</div>
          <p style={{ fontSize: 12, marginTop: -4, marginBottom: 8 }}>
            Average final confidence (model self-report averaged with computed evidence strength) at each cycle
            index, across every campaign.
          </p>
          {confidenceData.length === 0 ? (
            <div className="empty-state">No cycles run yet.</div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={confidenceData} margin={{ top: 8, right: 16, left: -16, bottom: 0 }}>
                <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                <XAxis dataKey="cycle" stroke="var(--chart-ink-muted)" fontSize={12} tickLine={false} axisLine={{ stroke: "var(--chart-axis)" }} />
                <YAxis
                  stroke="var(--chart-ink-muted)"
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                  width={36}
                  tickFormatter={(v) => `${v}%`}
                />
                <Tooltip
                  contentStyle={{ background: "var(--bg-elevated)", border: "1px solid var(--panel-border)", borderRadius: 8, fontSize: 12 }}
                  formatter={(v: number) => [`${v}%`, "Avg confidence"]}
                />
                <Line
                  type="monotone"
                  dataKey="avgConfidence"
                  stroke="var(--series-1)"
                  strokeWidth={2}
                  dot={{ r: 4, strokeWidth: 2, stroke: "var(--panel)", fill: "var(--series-1)" }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="card">
        <div className="section-title">Guardrail interventions</div>
        <p style={{ fontSize: 12, marginTop: -4, marginBottom: 12 }}>
          Every time a bolder move got capped back down because the evidence, budget, or lack of movement didn't
          justify it - enforced in code after the model/mock decided, not just requested in the prompt.
        </p>
        <div className="stat-row">
          <div className="stat">
            <div className="stat-value">{guardrailCounts.evidence}</div>
            <div className="stat-label">Evidence guardrail</div>
          </div>
          <div className="stat">
            <div className="stat-value">{guardrailCounts.budget}</div>
            <div className="stat-label">Budget guardrail</div>
          </div>
          <div className="stat">
            <div className="stat-value">{guardrailCounts.plateau}</div>
            <div className="stat-label">Plateau escalation</div>
          </div>
        </div>
      </div>
    </div>
  );
}
