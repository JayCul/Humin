"use client";

import type { Decision } from "@/lib/api";

const PHASE_LABEL: Record<string, string> = {
  perceive: "Perceive",
  remember: "Remember (Muninn)",
  think: "Think (Huginn)",
  act: "Act",
  learn: "Learn",
};

export default function AgentTraceLog({ decisions }: { decisions: Decision[] }) {
  if (decisions.length === 0) {
    return <div className="empty-state">No decisions logged yet.</div>;
  }

  const byCycle = new Map<number, Decision[]>();
  for (const d of decisions) {
    const list = byCycle.get(d.cycle) ?? [];
    list.push(d);
    byCycle.set(d.cycle, list);
  }
  const cycles = Array.from(byCycle.keys()).sort((a, b) => b - a);

  return (
    <div>
      {cycles.map((cycle) => (
        <div className="trace-cycle" key={cycle}>
          <h3>Cycle {cycle}</h3>
          {byCycle
            .get(cycle)!
            .sort((a, b) => a.created_at.localeCompare(b.created_at))
            .map((d) => (
              <div className="trace-phase" data-phase={d.phase} key={d.id}>
                <div className="trace-phase-label">{PHASE_LABEL[d.phase] ?? d.phase}</div>
                <p>{d.summary}</p>
              </div>
            ))}
        </div>
      ))}
    </div>
  );
}
