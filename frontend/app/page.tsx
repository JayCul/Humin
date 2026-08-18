"use client";

import { useEffect, useState } from "react";
import { api, type Campaign, type PerformancePoint, type SchedulerStatus } from "@/lib/api";
import CampaignComparisonChart from "@/app/components/CampaignComparisonChart";
import Modal from "@/app/components/Modal";

const GOALS = ["awareness", "conversion", "retention"];

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.round(seconds / 60)}m ago`;
}

function timeUntil(iso: string | null): string {
  if (!iso) return " - ";
  const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  if (seconds <= 0) return "any moment";
  if (seconds < 60) return `${seconds}s`;
  return `${Math.round(seconds / 60)}m`;
}

export default function DashboardPage() {
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [performanceByCampaign, setPerformanceByCampaign] = useState<Record<string, PerformancePoint[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [schedulerStatus, setSchedulerStatus] = useState<SchedulerStatus | null>(null);
  const [schedulerBusy, setSchedulerBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [form, setForm] = useState({
    name: "",
    product: "",
    audience_segment: "",
    goal: "conversion",
    tone: "confident, plain-spoken",
    region: "us-east",
    budget_usd: "",
    approval_mode: "autonomous" as "autonomous" | "review",
  });

  async function load() {
    try {
      const list = await api.listCampaigns();
      setCampaigns(list);
      setError(null);

      const entries = await Promise.all(
        list.map(async (c) => [c.id, await api.getPerformance(c.id).catch(() => [])] as const)
      );
      setPerformanceByCampaign(Object.fromEntries(entries));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function loadSchedulerStatus() {
    try {
      setSchedulerStatus(await api.getSchedulerStatus());
    } catch {
      // non-fatal - scheduler panel just won't render live data
    }
  }

  useEffect(() => {
    load();
    loadSchedulerStatus();
    const interval = setInterval(() => {
      loadSchedulerStatus();
      load();
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  async function handleToggleScheduler() {
    setSchedulerBusy(true);
    try {
      if (schedulerStatus?.enabled) {
        setSchedulerStatus(await api.stopScheduler());
      } else {
        setSchedulerStatus(await api.startScheduler());
      }
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSchedulerBusy(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      await api.createCampaign({
        ...form,
        budget_usd: form.budget_usd.trim() === "" ? null : Number(form.budget_usd),
      });
      setShowForm(false);
      setForm({ ...form, name: "", product: "", audience_segment: "", budget_usd: "", approval_mode: "autonomous" });
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  }

  const allPerformance = Object.values(performanceByCampaign).flat();
  const activeCount = campaigns?.filter((c) => c.status === "active").length ?? 0;
  const totalConversions = allPerformance.reduce((sum, p) => sum + p.conversions, 0);
  const totalSpend = allPerformance.reduce((sum, p) => sum + p.spend_usd, 0);
  const totalImpressions = allPerformance.reduce((sum, p) => sum + p.impressions, 0);
  const totalClicks = allPerformance.reduce((sum, p) => sum + p.clicks, 0);
  const fleetCtr = totalImpressions > 0 ? (totalClicks / totalImpressions) * 100 : 0;

  const filteredCampaigns = (campaigns ?? []).filter((c) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return [c.name, c.product, c.audience_segment, c.region].some((f) => f.toLowerCase().includes(q));
  });

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24, gap: 16 }}>
        <div>
          <h1>Ad campaigns</h1>
          <p>Each card is an agent watching, remembering, and adjusting an ad campaign on its own.</p>
        </div>
        <div className="search-row" style={{ flexWrap: "nowrap" }}>
          <input
            className="search-input"
            placeholder="Search ad campaigns…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="btn" onClick={() => setShowForm(true)}>
            + New ad campaign
          </button>
        </div>
      </div>

      {campaigns && campaigns.length > 0 && (
        <div className="kpi-row">
          <div className="card kpi-card">
            <span className="icon-badge icon-badge-teal">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="6 3 20 12 6 21 6 3" />
              </svg>
            </span>
            <div>
              <div className="kpi-value">{activeCount}</div>
              <div className="kpi-label">Active ad campaigns</div>
            </div>
          </div>
          <div className="card kpi-card">
            <span className="icon-badge icon-badge-gold">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 4l7.07 16.97 2.51-7.39 7.39-2.51z" />
              </svg>
            </span>
            <div>
              <div className="kpi-value">{fleetCtr.toFixed(2)}%</div>
              <div className="kpi-label">Fleet avg CTR</div>
            </div>
          </div>
          <div className="card kpi-card">
            <span className="icon-badge icon-badge-green">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </span>
            <div>
              <div className="kpi-value">{totalConversions.toLocaleString()}</div>
              <div className="kpi-label">Total conversions</div>
            </div>
          </div>
          <div className="card kpi-card">
            <span className="icon-badge icon-badge-rose">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
              </svg>
            </span>
            <div>
              <div className="kpi-value">${totalSpend.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
              <div className="kpi-label">Total spend</div>
            </div>
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 24, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <strong>Autonomous mode {schedulerStatus?.enabled ? " - ON" : " - off"}</strong>
          <p style={{ margin: "4px 0 0", fontSize: 13 }}>
            {schedulerStatus?.enabled ? (
              <>
                Running every {schedulerStatus.interval_seconds}s · last tick {timeAgo(schedulerStatus.last_run_at)}
                {schedulerStatus.last_run_summary
                  ? ` (${schedulerStatus.last_run_summary.ran} campaign(s) ran, ${schedulerStatus.last_run_summary.errors} error(s))`
                  : ""}{" "}
                · next in {timeUntil(schedulerStatus.next_run_at)}
              </>
            ) : (
              "Off - cycles only run when you click \"Run next cycle\", or via the AWS Lambda + EventBridge schedule in production."
            )}
          </p>
        </div>
        <button className="btn btn-ghost" onClick={handleToggleScheduler} disabled={schedulerBusy}>
          {schedulerBusy ? "…" : schedulerStatus?.enabled ? "Disable autonomous mode" : "▶ Enable autonomous mode"}
        </button>
      </div>

      {error && (
        <div className="card" style={{ borderColor: "var(--rose)", marginBottom: 16 }}>
          <p style={{ color: "var(--rose)" }}>
            Couldn't reach the backend ({error}). Is it running at{" "}
            <code>{process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api"}</code>?
          </p>
        </div>
      )}

      <Modal open={showForm} onClose={() => setShowForm(false)} title="New ad campaign">
        <form onSubmit={handleCreate}>
          <div className="form-grid">
            <div>
              <label>Ad campaign name</label>
              <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div>
              <label>Product</label>
              <input required value={form.product} onChange={(e) => setForm({ ...form, product: e.target.value })} />
            </div>
            <div>
              <label>Audience segment</label>
              <input
                required
                value={form.audience_segment}
                onChange={(e) => setForm({ ...form, audience_segment: e.target.value })}
              />
            </div>
            <div>
              <label>Goal</label>
              <select value={form.goal} onChange={(e) => setForm({ ...form, goal: e.target.value })}>
                {GOALS.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label>Region</label>
              <input value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })} />
            </div>
            <div>
              <label>Tone</label>
              <input value={form.tone} onChange={(e) => setForm({ ...form, tone: e.target.value })} />
            </div>
            <div>
              <label>Budget cap (USD, optional)</label>
              <input
                type="number"
                min="0"
                step="1"
                placeholder="unlimited"
                value={form.budget_usd}
                onChange={(e) => setForm({ ...form, budget_usd: e.target.value })}
              />
            </div>
          </div>

          <div style={{ marginTop: 16 }}>
            <label>Content review</label>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                className={`btn ${form.approval_mode === "autonomous" ? "" : "btn-ghost"}`}
                onClick={() => setForm({ ...form, approval_mode: "autonomous" })}
                style={{ flex: 1 }}
              >
                Autonomous
              </button>
              <button
                type="button"
                className={`btn ${form.approval_mode === "review" ? "" : "btn-ghost"}`}
                onClick={() => setForm({ ...form, approval_mode: "review" })}
                style={{ flex: 1 }}
              >
                Human review
              </button>
            </div>
            <p style={{ margin: "6px 0 0", fontSize: 12 }}>
              {form.approval_mode === "review"
                ? "Every new draft (from the first cycle onward) waits for your approval before it publishes. Discard it or send it back with feedback for a redraft."
                : "The agent publishes each cycle's content the moment it's drafted, no human step in the loop."}
            </p>
          </div>

          <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
            <button className="btn" type="submit" disabled={creating}>
              {creating ? "Creating…" : "Create ad campaign"}
            </button>
            <button className="btn btn-ghost" type="button" onClick={() => setShowForm(false)}>
              Cancel
            </button>
          </div>
        </form>
      </Modal>

      {campaigns === null && !error && <div className="empty-state">Loading…</div>}
      {campaigns && campaigns.length === 0 && (
        <div className="card empty-state">
          No ad campaigns yet. Run <code>python scripts/seed.py</code> in the backend, or create one above.
        </div>
      )}

      {campaigns && campaigns.length > 0 && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div className="section-title">Ad campaigns compared</div>
          <CampaignComparisonChart campaigns={campaigns} performanceByCampaign={performanceByCampaign} />
        </div>
      )}

      {campaigns && campaigns.length > 0 && filteredCampaigns.length === 0 && (
        <div className="card empty-state">No ad campaigns match “{query}”.</div>
      )}

      <div className="campaign-grid">
        {filteredCampaigns.map((c) => (
          <a className="card campaign-card" href={`/campaign/${c.id}`} key={c.id}>
            <span className="badge badge-region">{c.region}</span>
            {c.approval_mode === "review" && (
              <span className="badge" style={{ marginLeft: 6 }}>
                review
              </span>
            )}
            <h3 style={{ marginTop: 10 }}>{c.name}</h3>
            <p>{c.product}</p>
            <p style={{ fontSize: 12 }}>
              {c.audience_segment} · {c.goal}
              {c.budget_usd != null ? ` · budget $${c.budget_usd.toFixed(0)}` : ""}
            </p>
          </a>
        ))}
      </div>
    </div>
  );
}
