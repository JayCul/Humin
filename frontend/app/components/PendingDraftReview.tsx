"use client";

import { useState } from "react";
import { api, type ContentPiece } from "@/lib/api";
import AdCreative from "@/app/components/AdCreative";

export default function PendingDraftReview({
  campaignId,
  draft,
  onResolved,
}: {
  campaignId: string;
  draft: ContentPiece;
  onResolved: () => void | Promise<void>;
}) {
  const [headline, setHeadline] = useState(draft.headline);
  const [body, setBody] = useState(draft.body);
  const [image, setImage] = useState({
    url: draft.image_data_url,
    source: draft.image_source,
    prompt: draft.image_prompt,
  });
  const [busy, setBusy] = useState<"approve" | "regenerate" | "discard" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedback, setFeedback] = useState("");

  const edited = headline !== draft.headline || body !== draft.body;

  async function run(action: "approve" | "regenerate" | "discard", fn: () => Promise<unknown>) {
    setBusy(action);
    setError(null);
    try {
      await fn();
      await onResolved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="review-banner">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <span className="badge" style={{ color: "var(--gold)", borderColor: "color-mix(in srgb, var(--gold) 40%, transparent)" }}>
          awaiting review · cycle {draft.cycle}
          {draft.version > 1 ? ` · v${draft.version}` : ""}
        </span>
        <span style={{ fontSize: 12, color: "var(--text-dim)" }}>{draft.channel}</span>
      </div>

      <p style={{ fontSize: 13, marginBottom: 12 }}>
        Huginn drafted this ad and is holding it for your sign-off before it publishes. Edit it directly, send it
        back with feedback for a redraft, or discard it outright.
      </p>

      <AdCreative
        campaignId={campaignId}
        contentId={draft.id}
        imageDataUrl={image.url}
        imageSource={image.source}
        imagePrompt={image.prompt}
        onUploaded={(updated) =>
          setImage({ url: updated.image_data_url, source: updated.image_source, prompt: updated.image_prompt })
        }
      />

      <div style={{ marginBottom: 10 }}>
        <label>Headline</label>
        <input
          value={headline}
          onChange={(e) => setHeadline(e.target.value)}
          style={{ width: "100%" }}
          disabled={busy !== null}
        />
      </div>
      <div style={{ marginBottom: 12 }}>
        <label>Body</label>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={3}
          style={{ width: "100%", resize: "vertical" }}
          disabled={busy !== null}
        />
      </div>

      {showFeedback && (
        <div style={{ marginBottom: 12 }}>
          <label>Feedback for the redraft (optional)</label>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={2}
            placeholder="e.g. make it punchier and mention the discount"
            style={{ width: "100%", resize: "vertical" }}
            disabled={busy !== null}
          />
        </div>
      )}

      {error && (
        <p style={{ color: "var(--rose)", fontSize: 13 }}>{error}</p>
      )}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button
          className="btn"
          disabled={busy !== null}
          onClick={() =>
            run("approve", () =>
              api.approveDraft(campaignId, edited ? { headline, body } : undefined)
            )
          }
        >
          {busy === "approve" ? "Publishing…" : edited ? "Approve edits & publish" : "Approve & publish"}
        </button>

        {!showFeedback ? (
          <button className="btn btn-ghost" disabled={busy !== null} onClick={() => setShowFeedback(true)}>
            Regenerate with feedback
          </button>
        ) : (
          <>
            <button
              className="btn btn-ghost"
              disabled={busy !== null}
              onClick={() => run("regenerate", () => api.regenerateDraft(campaignId, feedback.trim() || undefined))}
            >
              {busy === "regenerate" ? "Redrafting…" : "Send for redraft"}
            </button>
            <button
              className="btn btn-ghost"
              disabled={busy !== null}
              onClick={() => {
                setShowFeedback(false);
                setFeedback("");
              }}
            >
              Cancel
            </button>
          </>
        )}

        <button
          className="btn btn-ghost"
          style={{ color: "var(--rose)", marginLeft: "auto" }}
          disabled={busy !== null}
          onClick={() => run("discard", () => api.discardDraft(campaignId))}
        >
          {busy === "discard" ? "Discarding…" : "Discard"}
        </button>
      </div>
    </div>
  );
}
