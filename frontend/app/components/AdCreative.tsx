"use client";

import { useRef, useState } from "react";
import { api, type ContentPiece } from "@/lib/api";

export default function AdCreative({
  campaignId,
  contentId,
  imageDataUrl,
  imageSource,
  imagePrompt,
  onUploaded,
}: {
  campaignId: string;
  contentId: string;
  imageDataUrl: string | null;
  imageSource: "generated" | "uploaded" | null;
  imagePrompt: string | null;
  onUploaded: (updated: ContentPiece) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const updated = await api.uploadContentImage(campaignId, contentId, file);
      onUploaded(updated);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div style={{ marginBottom: 14 }}>
      {imageDataUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={imageDataUrl}
          alt="Ad creative"
          style={{ width: "100%", borderRadius: 10, display: "block", border: "1px solid var(--panel-border)" }}
        />
      ) : (
        <div className="empty-state" style={{ padding: 20 }}>
          No creative image yet.
        </div>
      )}

      {imagePrompt && imageSource === "generated" && (
        <p style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 6, fontStyle: "italic" }}>
          Visual direction (Huginn): {imagePrompt}
        </p>
      )}
      {imageSource === "uploaded" && (
        <p style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 6 }}>Uploaded creative.</p>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          onChange={handleFile}
          disabled={uploading}
          style={{ fontSize: 12, maxWidth: "100%" }}
        />
        {uploading && <span style={{ fontSize: 12, color: "var(--text-dim)" }}>Uploading…</span>}
      </div>
      {error && <p style={{ color: "var(--rose)", fontSize: 12, marginTop: 4 }}>{error}</p>}
    </div>
  );
}
