"use client";

import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Decision, PerformancePoint, Strategy } from "@/lib/api";

type MergedPoint = {
  cycle: number;
  ctrPct: number;
  conversions: number;
  spend: number;
  confidencePct: number | null;
};

function mergeData(performance: PerformancePoint[], decisions: Decision[]): MergedPoint[] {
  const confidenceByCycle = new Map<number, number>();
  for (const d of decisions) {
    if (d.phase === "think") {
      const s = d.detail as unknown as Strategy;
      if (typeof s?.confidence === "number") confidenceByCycle.set(d.cycle, s.confidence);
    }
  }
  return performance.map((p) => ({
    cycle: p.cycle,
    ctrPct: Number((p.ctr * 100).toFixed(2)),
    conversions: p.conversions,
    spend: Number(p.spend_usd.toFixed(2)),
    confidencePct: confidenceByCycle.has(p.cycle) ? Math.round((confidenceByCycle.get(p.cycle) as number) * 100) : null,
  }));
}

function MiniLineChart({
  title,
  dataKey,
  data,
  formatValue,
}: {
  title: string;
  dataKey: keyof MergedPoint;
  data: MergedPoint[];
  formatValue: (v: number) => string;
}) {
  return (
    <div>
      <div className="chart-mini-title">{title}</div>
      <ResponsiveContainer width="100%" height={140}>
        <LineChart data={data} margin={{ top: 4, right: 12, left: -16, bottom: 0 }}>
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis
            dataKey="cycle"
            tickFormatter={(c) => `C${c}`}
            stroke="var(--chart-ink-muted)"
            fontSize={11}
            tickLine={false}
            axisLine={{ stroke: "var(--chart-axis)" }}
          />
          <YAxis stroke="var(--chart-ink-muted)" fontSize={11} tickLine={false} axisLine={false} width={38} />
          <Tooltip
            formatter={(v: number) => [formatValue(v), title]}
            labelFormatter={(c) => `Cycle ${c}`}
            contentStyle={{
              background: "var(--bg-elevated)",
              border: "1px solid var(--panel-border)",
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          <Line
            type="monotone"
            dataKey={dataKey}
            stroke="var(--series-1)"
            strokeWidth={2}
            dot={{ r: 4, strokeWidth: 2, stroke: "var(--panel)", fill: "var(--series-1)" }}
            connectNulls
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function PerformanceChart({
  performance,
  decisions,
}: {
  performance: PerformancePoint[];
  decisions: Decision[];
}) {
  const [view, setView] = useState<"chart" | "table">("chart");

  if (performance.length === 0) {
    return <div className="empty-state">No cycles run yet - run one to see performance appear here.</div>;
  }

  const data = mergeData(performance, decisions);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
        <button className="chart-view-toggle" onClick={() => setView(view === "chart" ? "table" : "chart")}>
          {view === "chart" ? "View as table" : "View as chart"}
        </button>
      </div>

      {view === "chart" ? (
        <div className="chart-small-multiples">
          <MiniLineChart title="Click-through rate" dataKey="ctrPct" data={data} formatValue={(v) => `${v}%`} />
          <MiniLineChart title="Conversions" dataKey="conversions" data={data} formatValue={(v) => `${v}`} />
          <MiniLineChart title="Spend" dataKey="spend" data={data} formatValue={(v) => `$${v}`} />
          <MiniLineChart
            title="Agent confidence"
            dataKey="confidencePct"
            data={data}
            formatValue={(v) => `${v}%`}
          />
        </div>
      ) : (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Cycle</th>
                <th>CTR</th>
                <th>Conversions</th>
                <th>Spend</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {data.map((d) => (
                <tr key={d.cycle}>
                  <td>C{d.cycle}</td>
                  <td>{d.ctrPct.toFixed(2)}%</td>
                  <td>{d.conversions}</td>
                  <td>${d.spend.toFixed(2)}</td>
                  <td>{d.confidencePct != null ? `${d.confidencePct}%` : " - "}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
