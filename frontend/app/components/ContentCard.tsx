"use client";

import { useEffect, useState } from "react";
import { api, type ContentPiece, type Decision, type Strategy } from "@/lib/api";
import AdCreative from "@/app/components/AdCreative";

const DECISION_LABEL: Record<string, string> = {
  keep: "keep",
  tweak: "tweak",
  pivot_angle: "pivot · angle",
  pivot_channel: "pivot · channel",
  kill: "kill",
};

export default function ContentCard({ campaignId, decisions }: { campaignId: string; decisions: Decision[] }) {
  const thinkDecisions = decisions.filter((d) => d.phase === "think");
  const latest = thinkDecisions[thinkDecisions.length - 1];

  // A reviewer may have edited the headline/body after this think decision
  // was logged (human-in-the-loop review) - the most recent "act" entry's
  // detail carries the final edited text when that happened, so prefer it
  // over the AI's first-pass draft for display. Every "act" log also
  // carries content_id, which is what lets us fetch the actual creative
  // image separately (see AdCreative / api.getContent) - the image itself
  // is deliberately never embedded in agent_decisions.detail, so it has to
  // be fetched on the side rather than read straight off `decisions`.
  const actDecisions = decisions.filter((d) => d.phase === "act");
  const latestAct = actDecisions[actDecisions.length - 1];
  const actDetail = latestAct?.detail as { headline?: string; body?: string; content_id?: string } | undefined;
  const contentId = actDetail?.content_id;

  const [content, setContent] = useState<ContentPiece | null>(null);

  useEffect(() => {
    if (!contentId) {
      setContent(null);
      return;
    }
    let cancelled = false;
    api
      .getContent(campaignId, contentId)
      .then((c) => {
        if (!cancelled) setContent(c);
      })
      .catch(() => {
        if (!cancelled) setContent(null);
      });
    return () => {
      cancelled = true;
    };
  }, [campaignId, contentId]);

  if (!latest) {
    return <div className="empty-state">No content generated yet.</div>;
  }

  const s = latest.detail as unknown as Strategy;
  const breakdown = s.confidence_breakdown;
  const displayHeadline = actDetail?.headline ?? s.headline;
  const displayBody = actDetail?.body ?? s.body;

  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 14, flexWrap: "wrap" }}>
        <span className={`badge badge-${s.decision}`}>{DECISION_LABEL[s.decision] ?? s.decision}</span>
        <span className="confidence-breakdown">
          {breakdown
            ? `confidence ${(breakdown.final * 100).toFixed(0)}% (model ${(breakdown.model_self_reported * 100).toFixed(0)}% · evidence ${(breakdown.evidence_strength * 100).toFixed(0)}%)`
            : `confidence ${(s.confidence * 100).toFixed(0)}%`}
        </span>
      </div>

      {s.decision !== "kill" && contentId && content && (
        <AdCreative
          campaignId={campaignId}
          contentId={contentId}
          imageDataUrl={content.image_data_url}
          imageSource={content.image_source}
          imagePrompt={content.image_prompt}
          onUploaded={setContent}
        />
      )}

      {s.decision !== "kill" && (
        <>
          <h3>{displayHeadline}</h3>
          <p>{displayBody}</p>
        </>
      )}

      <div style={{ marginTop: 14 }}>
        <div className="assessment-line">
          <span className="assessment-label">Performance</span>
          {s.performance_assessment}
        </div>
        <div className="assessment-line">
          <span className="assessment-label">Memory</span>
          {s.memory_assessment}
        </div>
        <div className="assessment-line">
          <span className="assessment-label">Trend</span>
          {s.trend_assessment}
        </div>
        <div className="assessment-line" style={{ fontStyle: "italic" }}>
          <span className="assessment-label">Synthesis</span>
          {s.rationale}
        </div>
      </div>

      {s.guardrail_notes && s.guardrail_notes.length > 0 && (
        <div className="guardrail-note">⚠ {s.guardrail_notes.join(" ")}</div>
      )}
    </div>
  );
}
