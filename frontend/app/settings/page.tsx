"use client";

import { useEffect, useState } from "react";
import { api, type SystemStatus } from "@/lib/api";

function ModeBadge({ mode }: { mode: "live" | "mock" }) {
  return (
    <span className={`badge ${mode === "live" ? "badge-keep" : "badge-tweak"}`}>{mode}</span>
  );
}

function CheckRow({ done, label, detail }: { done: boolean; label: string; detail: string }) {
  return (
    <div className="tool-row">
      <span className={`tool-check ${done ? "tool-check-yes" : "tool-check-no"}`}>{done ? "✓" : "–"}</span>
      <div>
        <div style={{ fontWeight: 600, fontSize: 14 }}>{label}</div>
        <div style={{ fontSize: 12, color: "var(--text-dim)" }}>{detail}</div>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dataBusy, setDataBusy] = useState<"reset" | "seed" | null>(null);
  const [dataMessage, setDataMessage] = useState<string | null>(null);

  function loadStatus() {
    api
      .getSystemStatus()
      .then(setStatus)
      .catch((e) => setError((e as Error).message));
  }

  useEffect(() => {
    loadStatus();
  }, []);

  async function handleReset() {
    const confirmed = window.confirm(
      "This permanently deletes every campaign, all generated content, and the full decision history. This can't be undone. Continue?"
    );
    if (!confirmed) return;
    setDataBusy("reset");
    setDataMessage(null);
    try {
      const result = await api.resetAllData();
      setDataMessage(`Cleared. ${result.campaigns.length} campaign(s) remain.`);
      loadStatus();
    } catch (e) {
      setDataMessage(`Failed: ${(e as Error).message}`);
    } finally {
      setDataBusy(null);
    }
  }

  async function handleSeedDemo() {
    setDataBusy("seed");
    setDataMessage(null);
    try {
      const result = await api.seedDemoData();
      setDataMessage(`Loaded ${result.campaigns.length} demo campaign(s), each run through a few cycles.`);
      loadStatus();
    } catch (e) {
      setDataMessage(`Failed: ${(e as Error).message}`);
    } finally {
      setDataBusy(null);
    }
  }

  if (error) {
    return (
      <div className="card">
        <p style={{ color: "var(--rose)" }}>{error}</p>
      </div>
    );
  }

  if (!status) {
    return <div className="empty-state">Loading…</div>;
  }

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1>Settings</h1>
        <p>Live integration status - what&apos;s actually wired in right now, not just documented.</p>
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="section-title">Data</div>
        <p style={{ fontSize: 13, marginTop: -4 }}>
          Start clean with no campaigns, or load a populated set of demo campaigns already run through a few
          cycles — useful for a quick look at the dashboard without waiting on real cycles.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
          <button className="btn" onClick={handleSeedDemo} disabled={dataBusy !== null}>
            {dataBusy === "seed" ? "Loading demo data…" : "Load demo data"}
          </button>
          <button className="btn btn-ghost" onClick={handleReset} disabled={dataBusy !== null}>
            {dataBusy === "reset" ? "Clearing…" : "Clear all data"}
          </button>
        </div>
        {dataMessage && (
          <p style={{ fontSize: 13, marginTop: 10, color: dataMessage.startsWith("Failed") ? "var(--rose)" : "var(--green)" }}>
            {dataMessage}
          </p>
        )}
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 20 }}>
        <div className="card">
          <div className="section-title">CockroachDB</div>
          <div className="settings-row">
            <span>Mode</span>
            <ModeBadge mode={status.cockroachdb.mode} />
          </div>
          <div className="settings-row">
            <span>Connection configured</span>
            <span>{status.cockroachdb.url_configured ? "yes" : "no (using in-memory store)"}</span>
          </div>
          <div className="settings-row">
            <span>Cloud Managed MCP Server</span>
            <span>
              {status.cockroachdb.mcp_configured
                ? status.cockroachdb.mcp_tools.length > 0
                  ? `connected · ${status.cockroachdb.mcp_tools.length} tool(s)`
                  : "configured, unreachable"
                : "not configured"}
            </span>
          </div>
          {status.cockroachdb.mcp_tools.length > 0 && (
            <div className="settings-row" style={{ alignItems: "flex-start" }}>
              <span>Discovered tools</span>
              <span style={{ textAlign: "right", fontSize: 12 }}>{status.cockroachdb.mcp_tools.join(", ")}</span>
            </div>
          )}
        </div>

        <div className="card">
          <div className="section-title">Amazon Bedrock</div>
          <div className="settings-row">
            <span>Mode</span>
            <ModeBadge mode={status.bedrock.mode} />
          </div>
          <div className="settings-row">
            <span>Text model</span>
            <span style={{ fontSize: 12 }}>{status.bedrock.text_model_id}</span>
          </div>
          <div className="settings-row">
            <span>Embedding model</span>
            <span style={{ fontSize: 12 }}>{status.bedrock.embedding_model_id}</span>
          </div>
          <div className="settings-row">
            <span>Embedding dimensions</span>
            <span>{status.bedrock.embedding_dimensions}</span>
          </div>
          <div className="settings-row">
            <span>AWS region</span>
            <span>{status.bedrock.aws_region}</span>
          </div>
        </div>

        <div className="card">
          <div className="section-title">Trend signal</div>
          <div className="settings-row">
            <span>Provider</span>
            <span>{status.trends.provider === "google_trends" ? "Google Trends (live)" : "mock (vertical-aware topic pools)"}</span>
          </div>
        </div>

        <div className="card">
          <div className="section-title">Scheduler</div>
          <div className="settings-row">
            <span>Autonomous mode</span>
            <span>{status.scheduler.enabled ? `on · every ${status.scheduler.interval_seconds}s` : "off"}</span>
          </div>
          <div className="settings-row">
            <span>Default interval</span>
            <span>{status.scheduler.default_interval_seconds}s</span>
          </div>
          <div className="settings-row">
            <span>Last tick</span>
            <span>
              {status.scheduler.last_run_summary
                ? `${status.scheduler.last_run_summary.ran} ran, ${status.scheduler.last_run_summary.errors} errors`
                : " - "}
            </span>
          </div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <div className="card">
          <div className="section-title">CockroachDB tools (hackathon requirement: ≥2)</div>
          <CheckRow
            done
            label="Distributed Vector Indexing"
            detail="content_pieces.embedding VECTOR(1024) + vector index - every Remember phase queries it"
          />
          <CheckRow
            done={status.cockroachdb.mcp_tools.length > 0}
            label="Cloud Managed MCP Server"
            detail={
              status.cockroachdb.mcp_tools.length > 0
                ? `connected - routes vector recall through: ${status.cockroachdb.mcp_tools.join(", ")}`
                : status.cockroachdb.mcp_configured
                  ? "configured but not reachable right now - falling back to the direct driver"
                  : "real MCP client implemented (app/db/mcp_client.py) - set COCKROACHDB_MCP_URL to activate"
            }
          />
          <CheckRow done={false} label="ccloud CLI" detail="not used - cluster ops, not part of the runtime agent loop" />
          <CheckRow done={false} label="Agent Skills Repo" detail="not used - candidate for future packaging" />
        </div>

        <div className="card">
          <div className="section-title">AWS services (hackathon requirement: ≥1)</div>
          <CheckRow done label="Amazon Bedrock" detail="Think phase reasoning + Remember/Act embeddings" />
          <CheckRow done label="AWS Lambda" detail="scheduled entry point - infra/lambda/handler.py" />
          <CheckRow done label="Amazon EventBridge" detail="puts the Lambda on a recurring schedule in production" />
        </div>
      </div>
    </div>
  );
}
