"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { api, type Campaign, type ContentPiece, type Decision, type PerformancePoint } from "@/lib/api";
import PerformanceChart from "@/app/components/PerformanceChart";
import AgentTraceLog from "@/app/components/AgentTraceLog";
import MemoryExplorer from "@/app/components/MemoryExplorer";
import ContentCard from "@/app/components/ContentCard";
import PendingDraftReview from "@/app/components/PendingDraftReview";

export default function CampaignDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [performance, setPerformance] = useState<PerformancePoint[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [pendingDraft, setPendingDraft] = useState<ContentPiece | null>(null);
  const [running, setRunning] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [c, p, d] = await Promise.all([api.getCampaign(id), api.getPerformance(id), api.getDecisions(id)]);
      setCampaign(c);
      setPerformance(p);
      setDecisions(d);
      setError(null);
      if (c.approval_mode === "review") {
        setPendingDraft(await api.getPendingDraft(id).catch(() => null));
      } else {
        setPendingDraft(null);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleRunCycle() {
    setRunning(true);
    try {
      await api.runCycle(id);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  async function handleResume() {
    setPausing(true);
    try {
      await api.resumeCampaign(id);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPausing(false);
    }
  }

  async function handlePause() {
    setPausing(true);
    try {
      await api.pauseCampaign(id);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPausing(false);
    }
  }

  if (error) {
    return (
      <div className="card">
        <p style={{ color: "var(--rose)" }}>{error}</p>
        <a href="/">← back to ad campaigns</a>
      </div>
    );
  }

  if (!campaign) {
    return <div className="empty-state">Loading…</div>;
  }

  const latest = performance[performance.length - 1];

  return (
    <div>
      <a href="/" style={{ fontSize: 13, color: "var(--text-dim)" }}>
        ← all ad campaigns
      </a>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", margin: "8px 0 24px" }}>
        <div>
          <span className="badge badge-region">{campaign.region}</span>
          <h1 style={{ marginTop: 8 }}>{campaign.name}</h1>
          <p>
            {campaign.product} · {campaign.audience_segment} · goal: {campaign.goal}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {campaign.status === "active" && (
            <button className="btn btn-ghost" onClick={handlePause} disabled={pausing || running}>
              {pausing ? "…" : "Pause"}
            </button>
          )}
          <button
            className="btn"
            onClick={handleRunCycle}
            disabled={running || campaign.status !== "active" || pendingDraft !== null}
            title={pendingDraft ? "Resolve the pending draft below before running another cycle" : undefined}
          >
            {running ? "Running cycle…" : "▶ Run next cycle"}
          </button>
        </div>
      </div>

      {pendingDraft && (
        <PendingDraftReview key={pendingDraft.id} campaignId={id} draft={pendingDraft} onResolved={load} />
      )}

      {campaign.status === "paused" && (
        <div className="paused-banner">
          <div>
            <strong>Ad campaign paused.</strong> The agent recommended stopping this direction - see the
            latest reasoning below for why, or resume to keep iterating anyway.
          </div>
          <button className="btn" onClick={handleResume} disabled={pausing}>
            {pausing ? "…" : "Resume ad campaign"}
          </button>
        </div>
      )}

      {latest && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="stat-row">
            <div className="stat">
              <div className="stat-value">{performance.length}</div>
              <div className="stat-label">Cycles run</div>
            </div>
            <div className="stat">
              <div className="stat-value">{(latest.ctr * 100).toFixed(2)}%</div>
              <div className="stat-label">Latest CTR</div>
            </div>
            <div className="stat">
              <div className="stat-value">{latest.conversions}</div>
              <div className="stat-label">Latest conversions</div>
            </div>
            <div className="stat">
              <div className="stat-value">${latest.spend_usd.toFixed(0)}</div>
              <div className="stat-label">Latest spend</div>
            </div>
          </div>

          {campaign.budget_usd != null && (
            <div style={{ marginTop: 16 }}>
              {(() => {
                const totalSpend = performance.reduce((sum, p) => sum + p.spend_usd, 0);
                const pct = Math.min(100, (totalSpend / campaign.budget_usd!) * 100);
                const overBudget = totalSpend >= campaign.budget_usd!;
                return (
                  <>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--text-dim)", marginBottom: 4 }}>
                      <span>Budget: ${totalSpend.toFixed(0)} of ${campaign.budget_usd!.toFixed(0)} spent</span>
                      <span style={overBudget ? { color: "var(--rose)", fontWeight: 700 } : undefined}>
                        {overBudget ? "exhausted" : `${pct.toFixed(0)}%`}
                      </span>
                    </div>
                    <div className="similarity-bar" style={{ width: "100%" }}>
                      <div
                        className="similarity-fill"
                        style={{ width: `${pct}%`, background: overBudget ? "var(--rose)" : undefined }}
                      />
                    </div>
                  </>
                );
              })()}
            </div>
          )}
        </div>
      )}

      <div className="grid campaign-detail-grid" style={{ alignItems: "start" }}>
        <div className="grid" style={{ gap: 20 }}>
          <div className="card">
            <div className="section-title">Performance over time</div>
            <PerformanceChart performance={performance} decisions={decisions} />
          </div>
          <div className="card">
            <div className="section-title">Agent reasoning trail</div>
            <AgentTraceLog decisions={decisions} />
          </div>
        </div>

        <div className="grid" style={{ gap: 20 }}>
          <div className="card">
            <div className="section-title">Latest ad copy (Huginn)</div>
            <ContentCard campaignId={id} decisions={decisions} />
          </div>
          <div className="card">
            <div className="section-title">Recalled from memory (Muninn)</div>
            <MemoryExplorer decisions={decisions} />
          </div>
        </div>
      </div>
    </div>
  );
}
