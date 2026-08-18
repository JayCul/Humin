"use client";

import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Campaign, PerformancePoint } from "@/lib/api";

// Fixed slot order - the CVD-safety mechanism. Never reassign by rank/filter;
// each campaign keeps its slot (by creation order) for as long as it exists.
const SERIES_COLORS = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
  "var(--series-6)",
  "var(--series-7)",
  "var(--series-8)",
];
const MAX_SERIES = SERIES_COLORS.length;

export default function CampaignComparisonChart({
  campaigns,
  performanceByCampaign,
}: {
  campaigns: Campaign[];
  performanceByCampaign: Record<string, PerformancePoint[]>;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");

  const ordered = [...campaigns].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  );
  const withData = ordered.filter((c) => (performanceByCampaign[c.id] || []).length > 0);

  if (withData.length === 0) {
    return <div className="empty-state">No campaign has completed a cycle yet - run one to see it appear here.</div>;
  }

  const shown = withData.slice(0, MAX_SERIES);
  const hiddenCount = withData.length - shown.length;
  const colorFor = (campaignId: string) => SERIES_COLORS[ordered.findIndex((c) => c.id === campaignId) % MAX_SERIES];

  const maxCycle = Math.max(...withData.flatMap((c) => (performanceByCampaign[c.id] || []).map((p) => p.cycle)));
  const cycles = Array.from({ length: maxCycle }, (_, i) => i + 1);

  const chartData = cycles.map((cycle) => {
    const row: Record<string, number | string> = { cycle: `C${cycle}` };
    for (const c of shown) {
      const point = (performanceByCampaign[c.id] || []).find((p) => p.cycle === cycle);
      if (point) row[c.name] = Number((point.ctr * 100).toFixed(2));
    }
    return row;
  });

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12, gap: 12 }}>
        <p style={{ margin: 0, fontSize: 13, maxWidth: 520 }}>
          CTR by cycle, every campaign on one axis - this is where cross-campaign memory recall shows up
          visually: a campaign that borrows a proven angle from another jumps rather than drifts.
        </p>
        <button className="chart-view-toggle" onClick={() => setView(view === "chart" ? "table" : "chart")}>
          {view === "chart" ? "View as table" : "View as chart"}
        </button>
      </div>

      {hiddenCount > 0 && (
        <p style={{ fontSize: 12 }}>
          +{hiddenCount} more campaign{hiddenCount === 1 ? "" : "s"} not charted (8-series cap) - see table view
          for all.
        </p>
      )}

      {view === "chart" ? (
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData} margin={{ top: 8, right: 16, left: -16, bottom: 0 }}>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            <XAxis dataKey="cycle" stroke="var(--chart-ink-muted)" fontSize={12} tickLine={false} axisLine={{ stroke: "var(--chart-axis)" }} />
            <YAxis
              stroke="var(--chart-ink-muted)"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              width={40}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              contentStyle={{
                background: "var(--bg-elevated)",
                border: "1px solid var(--panel-border)",
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(v: number) => [`${v}%`, "CTR"]}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {shown.map((c) => (
              <Line
                key={c.id}
                type="monotone"
                dataKey={c.name}
                stroke={colorFor(c.id)}
                strokeWidth={2}
                dot={{ r: 4, strokeWidth: 2, stroke: "var(--panel)", fill: colorFor(c.id) }}
                connectNulls
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Cycle</th>
                {withData.map((c) => (
                  <th key={c.id}>{c.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cycles.map((cycle) => (
                <tr key={cycle}>
                  <td>C{cycle}</td>
                  {withData.map((c) => {
                    const point = (performanceByCampaign[c.id] || []).find((p) => p.cycle === cycle);
                    return <td key={c.id}>{point ? `${(point.ctr * 100).toFixed(2)}%` : " - "}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
