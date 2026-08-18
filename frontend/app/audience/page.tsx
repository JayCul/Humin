"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Campaign, type PerformancePoint } from "@/lib/api";

type SegmentRow = {
  segment: string;
  campaignCount: number;
  campaignNames: string[];
  totalImpressions: number;
  totalClicks: number;
  totalConversions: number;
  totalSpend: number;
};

const CHART_THRESHOLD = 6; // above this many segments, a table reads better than a bar chart

export default function AudiencePage() {
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [performanceByCampaign, setPerformanceByCampaign] = useState<Record<string, PerformancePoint[]>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const list = await api.listCampaigns();
        setCampaigns(list);
        const entries = await Promise.all(
          list.map(async (c) => [c.id, await api.getPerformance(c.id).catch(() => [])] as const)
        );
        setPerformanceByCampaign(Object.fromEntries(entries));
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

  const bySegment = new Map<string, SegmentRow>();
  for (const c of campaigns) {
    const row =
      bySegment.get(c.audience_segment) ??
      ({
        segment: c.audience_segment,
        campaignCount: 0,
        campaignNames: [],
        totalImpressions: 0,
        totalClicks: 0,
        totalConversions: 0,
        totalSpend: 0,
      } as SegmentRow);
    row.campaignCount += 1;
    row.campaignNames.push(c.name);
    for (const p of performanceByCampaign[c.id] || []) {
      row.totalImpressions += p.impressions;
      row.totalClicks += p.clicks;
      row.totalConversions += p.conversions;
      row.totalSpend += p.spend_usd;
    }
    bySegment.set(c.audience_segment, row);
  }

  const rows = Array.from(bySegment.values()).sort((a, b) => b.totalConversions - a.totalConversions);
  const reusedSegments = rows.filter((r) => r.campaignCount > 1);

  const chartData = rows.map((r) => ({
    segment: r.segment.length > 22 ? r.segment.slice(0, 20) + "…" : r.segment,
    fullSegment: r.segment,
    conversions: r.totalConversions,
  }));

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1>Audience</h1>
        <p>Every audience segment across the fleet, aggregated - and which ones show up more than once.</p>
      </div>

      {reusedSegments.length > 0 && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="section-title">Segments reused across campaigns</div>
          <p style={{ fontSize: 13 }}>
            {reusedSegments.map((r) => (
              <span key={r.segment}>
                <strong>{r.segment}</strong> - {r.campaignCount} campaigns ({r.campaignNames.join(", ")})
                <br />
              </span>
            ))}
          </p>
        </div>
      )}

      {rows.length === 0 ? (
        <div className="card empty-state">No campaigns yet.</div>
      ) : (
        <div className="card">
          <div className="section-title">Performance by audience segment</div>
          {rows.length <= CHART_THRESHOLD && (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={chartData} margin={{ top: 8, right: 16, left: -16, bottom: 8 }}>
                <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                <XAxis dataKey="segment" stroke="var(--chart-ink-muted)" fontSize={11} tickLine={false} axisLine={{ stroke: "var(--chart-axis)" }} />
                <YAxis stroke="var(--chart-ink-muted)" fontSize={12} tickLine={false} axisLine={false} width={32} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: "var(--bg-elevated)", border: "1px solid var(--panel-border)", borderRadius: 8, fontSize: 12 }}
                  labelFormatter={(_, payload) => payload?.[0]?.payload?.fullSegment ?? ""}
                  formatter={(v: number) => [v, "Conversions"]}
                />
                <Bar dataKey="conversions" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={40} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          )}

          <div className="data-table-wrap" style={{ marginTop: rows.length <= CHART_THRESHOLD ? 20 : 0 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Segment</th>
                  <th>Campaigns</th>
                  <th>Avg CTR</th>
                  <th>Conversions</th>
                  <th>Spend</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.segment}>
                    <td>{r.segment}</td>
                    <td>{r.campaignCount}</td>
                    <td>{r.totalImpressions > 0 ? ((r.totalClicks / r.totalImpressions) * 100).toFixed(2) : "0.00"}%</td>
                    <td>{r.totalConversions}</td>
                    <td>${r.totalSpend.toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
