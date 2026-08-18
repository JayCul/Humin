"""Synthetic ad-platform performance simulator.

Humin doesn't touch a real ad account - real spend/API keys aren't the point
of the hackathon, the memory+reasoning loop is. This module stands in for
"what would have happened" if the generated content had actually run,
producing impressions/clicks/conversions/spend that respond to:

  * the agent's own confidence in its last decision (higher confidence,
    better-targeted copy -> modestly better performance),
  * how bold this cycle's decision was - a full pivot (new angle or new
    channel) is noisier than a small tweak, which is noisier than staying
    the course, mirroring real creative-refresh volatility,
  * the live trend score (riding a hot trend gives a temporary lift),

so that over several cycles there's a real trajectory for the dashboard to
show and for the agent to react to next time.
"""
from __future__ import annotations

import random
from typing import Any

_PIVOT_DECISIONS = {"pivot_angle", "pivot_channel"}


def simulate_cycle(
    *,
    base_impressions: int = 8000,
    decision: str = "keep",
    confidence: float = 0.6,
    trend_score: float = 0.0,
    prior_ctr: float | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    rng = rng or random.Random()

    impressions = int(base_impressions * rng.uniform(0.85, 1.15))

    # Baseline CTR drifts around a prior; bolder moves add more variance, trend adds lift.
    baseline_ctr = prior_ctr if prior_ctr is not None else 0.022
    if decision in _PIVOT_DECISIONS:
        volatility = 0.010
    elif decision == "tweak":
        volatility = 0.006
    else:
        volatility = 0.004
    trend_lift = max(0.0, trend_score) * 0.006
    confidence_lift = (confidence - 0.5) * 0.006

    ctr = max(0.002, baseline_ctr + rng.gauss(0, volatility) + trend_lift + confidence_lift)
    clicks = int(impressions * ctr)

    conv_rate = max(0.01, min(0.35, 0.08 + rng.gauss(0, 0.02) + confidence_lift))
    conversions = int(clicks * conv_rate)

    cpc = round(rng.uniform(0.35, 1.10), 2)
    spend = round(clicks * cpc, 2)

    return {
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "spend_usd": spend,
        "ctr": round(ctr, 5),
        "conv_rate": round(conv_rate, 5),
    }


def trend_label(history: list[dict[str, Any]]) -> str:
    """Classify recent CTR trajectory as declining/flat/improving for the
    agent's 'perceive' phase."""
    if len(history) < 2:
        return "insufficient_data"
    recent = [float(h["ctr"]) for h in history[-3:] if h.get("ctr") is not None]
    if len(recent) < 2:
        return "insufficient_data"
    delta = recent[-1] - recent[0]
    if delta > 0.002:
        return "improving"
    if delta < -0.002:
        return "declining"
    return "flat"
