"use client";

import type { Decision, RecalledMemoryItem } from "@/lib/api";

export default function MemoryExplorer({ decisions }: { decisions: Decision[] }) {
  const rememberDecisions = decisions.filter((d) => d.phase === "remember");
  const latest = rememberDecisions[rememberDecisions.length - 1];

  if (!latest) {
    return <div className="empty-state">No recall performed yet.</div>;
  }

  const recalled = (latest.detail?.recalled as RecalledMemoryItem[] | undefined) ?? [];

  if (recalled.length === 0) {
    return (
      <div className="empty-state">
        Cold start - no precedent found in CockroachDB&apos;s vector index yet. Once other
        campaigns/cycles exist, similar ads will surface here.
      </div>
    );
  }

  return (
    <div>
      {recalled.map((r, i) => (
        <div className="memory-item" key={i}>
          <div>
            <div style={{ fontWeight: 600 }}>{r.headline}</div>
            <div style={{ fontSize: 12, color: "var(--text-dim)" }}>
              {r.campaign_name} · <span className="badge badge-region">{r.region}</span>
            </div>
            {r.outcome ? (
              <div style={{ fontSize: 12, color: "var(--green)", marginTop: 4 }}>
                {(r.outcome.ctr * 100).toFixed(2)}% CTR · {r.outcome.conversions} conversions
              </div>
            ) : (
              <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 4, fontStyle: "italic" }}>
                no completed outcome yet
              </div>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div className="similarity-bar">
              <div className="similarity-fill" style={{ width: `${Math.max(0, r.similarity) * 100}%` }} />
            </div>
            <span style={{ fontSize: 12, color: "var(--text-dim)" }}>{(r.similarity * 100).toFixed(0)}%</span>
          </div>
        </div>
      ))}
    </div>
  );
}
