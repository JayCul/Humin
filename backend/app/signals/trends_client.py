"""Real, read-only external grounding signal.

Provider is `google_trends` (via pytrends, unofficial but widely used) when
configured, else a small deterministic mock list so the agent loop and demo
never depend on an external service being reachable at the wrong moment.

This is intentionally the *only* live external call in the system besides
Bedrock - everything else (ad performance) is simulated, per the "simulator +
one real read-only signal" scope decision.

Both paths are vertical-aware: a raw branded product name ("CloudDesk
workspace app") is a bad Google Trends query (usually near-zero search
volume) and a worse key into a one-size-fits-all mock topic list - an
agricultural campaign has no business being told "AI-assisted shopping" is
trending. `_classify_vertical()` reads the campaign's product + audience
text and picks the pool/query term that's actually relevant to it.
"""
from __future__ import annotations

import logging
import random
import re
from typing import Any

from app.config import get_settings

logger = logging.getLogger("humin.trends")

# Keyword -> vertical. Checked in order; first match wins. Deliberately
# simple (substring match, no ML) - it only needs to be good enough to keep
# the trend signal in the right neighborhood, not a real classifier.
_VERTICAL_KEYWORDS: dict[str, list[str]] = {
    "agriculture": [
        "farm", "agri", "crop", "soil", "livestock", "harvest", "grower",
        "ranch", "irrigation", "seed", "pesticide", "fertilizer",
    ],
    "b2b_tech": [
        "workspace", "saas", "enterprise", "software", "platform",
        "developer", "cloud", "api", "b2b",
    ],
    "healthcare": ["clinic", "patient", "health", "medical", "care", "wellness"],
    "finance": ["bank", "invest", "finance", "loan", "payment", "insurance"],
}

# Mock topic pools, one per vertical, each (topic, base_score 0-1).
_TOPIC_POOLS: dict[str, list[tuple[str, float]]] = {
    "agriculture": [
        ("precision farming adoption", 0.68),
        ("input cost inflation", 0.74),
        ("regenerative agriculture", 0.59),
        ("farm labor shortages", 0.66),
        ("crop insurance changes", 0.48),
        ("equipment financing rates", 0.52),
    ],
    "b2b_tech": [
        ("AI-assisted workflows", 0.82),
        ("subscription fatigue", 0.42),
        ("remote-team tooling", 0.61),
        ("vendor consolidation", 0.55),
        ("data privacy scrutiny", 0.58),
    ],
    "healthcare": [
        ("telehealth adoption", 0.64),
        ("staffing shortages", 0.57),
        ("preventive care push", 0.5),
        ("patient portal usage", 0.46),
    ],
    "finance": [
        ("rate volatility", 0.6),
        ("fraud prevention spend", 0.53),
        ("embedded finance", 0.62),
        ("fee transparency scrutiny", 0.47),
    ],
    "retail": [
        ("sustainable packaging", 0.71),
        ("AI-assisted shopping", 0.88),
        ("local-first products", 0.55),
        ("creator collaborations", 0.63),
        ("back-to-school savings", 0.77),
    ],
}

# Representative category term to query Google Trends with, per vertical - # these return real search-volume data far more reliably than a branded
# product name does.
_VERTICAL_QUERY_TERMS: dict[str, str] = {
    "agriculture": "precision farming",
    "b2b_tech": "business software",
    "healthcare": "telehealth",
    "finance": "digital banking",
    "retail": "online shopping trends",
}

_DEFAULT_VERTICAL = "retail"


def _classify_vertical(product: str, audience_segment: str) -> str:
    # Whole-word matching, not substring - plain `kw in text` would let
    # "care" false-match inside "skincare", or "api" false-match inside
    # "therapist". Tokenizing avoids that class of bug entirely.
    tokens = set(re.findall(r"[a-z0-9]+", f"{product} {audience_segment}".lower()))
    # Naive de-pluralization so "clinics"/"loans"/"farms" still match their
    # singular keyword ("clinic"/"loan"/"farm") without a stemming dependency.
    tokens |= {t[:-1] for t in tokens if len(t) > 3 and t.endswith("s")}
    for vertical, keywords in _VERTICAL_KEYWORDS.items():
        if tokens & set(keywords):
            return vertical
    return _DEFAULT_VERTICAL


def _mock_signal(seed_key: str, vertical: str) -> dict[str, Any]:
    pool = _TOPIC_POOLS.get(vertical, _TOPIC_POOLS[_DEFAULT_VERTICAL])
    rng = random.Random(seed_key)
    topic, base_score = rng.choice(pool)
    score = max(0.0, min(1.0, base_score + rng.uniform(-0.15, 0.15)))
    return {"topic": topic, "source": "mock", "score": round(score, 4)}


def fetch_trend_signal(product: str, audience_segment: str, cycle: int) -> dict[str, Any]:
    settings = get_settings()
    vertical = _classify_vertical(product, audience_segment)
    seed_key = f"{product}:{audience_segment}:{cycle}"

    if settings.trends_provider != "google_trends":
        return _mock_signal(seed_key, vertical)

    try:
        from pytrends.request import TrendReq

        keyword = _VERTICAL_QUERY_TERMS.get(vertical, _VERTICAL_QUERY_TERMS[_DEFAULT_VERTICAL])
        pytrends = TrendReq(hl="en-US", tz=0)
        pytrends.build_payload([keyword], timeframe="now 7-d")
        df = pytrends.interest_over_time()
        if df.empty:
            raise ValueError("no data returned")
        score = float(df[keyword].iloc[-1]) / 100.0
        return {"topic": keyword, "source": "google_trends", "score": round(score, 4)}
    except Exception as exc:  # network/rate-limit/parsing failures shouldn't break a demo cycle
        logger.warning("google_trends fetch failed (%s), falling back to mock signal", exc)
        return _mock_signal(seed_key, vertical)
