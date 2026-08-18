"""Demo campaign definitions + the seeding routine — shared between
`scripts/seed.py` (CLI) and the `/api/system/seed-demo` endpoint (in-app
"Load demo data" button), so both stay in sync by construction.
"""
from __future__ import annotations

from typing import Any, Callable

from app.agent.orchestrator import run_cycle
from app.db.repository import Repository

DEMO_CAMPAIGNS: list[dict[str, Any]] = [
    {
        "name": "Fall Launch — Northeast",
        "product": "CloudDesk workspace app",
        "audience_segment": "remote-first small business teams",
        "goal": "conversion",
        "tone": "confident, plain-spoken",
        "region": "us-east",
    },
    {
        "name": "Fall Launch — West",
        "product": "CloudDesk workspace app",
        "audience_segment": "remote-first small business teams",
        "goal": "conversion",
        "tone": "confident, plain-spoken",
        "region": "us-west",
    },
    {
        "name": "EU Awareness Push",
        "product": "CloudDesk workspace app",
        "audience_segment": "hybrid teams in mid-size enterprises",
        "goal": "awareness",
        "tone": "polished, reassuring",
        "region": "eu-central",
    },
    {
        "name": "Trial Budget Test",
        "product": "CloudDesk workspace app",
        "audience_segment": "solo founders",
        "goal": "conversion",
        "tone": "scrappy, direct",
        "region": "us-east",
        # Tight on purpose: over CYCLES_PER_CAMPAIGN cycles this should visibly
        # run into the budget guardrail (near-limit downgrade, then a forced
        # 'kill' once exhausted) rather than just the evidence guardrail.
        "budget_usd": 180.0,
    },
]

CYCLES_PER_CAMPAIGN = 4


def run_seed(repo: Repository, log: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """Create the demo campaigns and run each through a few cycles. Returns
    the created campaign rows. `log` defaults to `print` for the CLI script;
    the API endpoint passes a no-op or a list-collecting logger instead."""
    created = []
    for spec in DEMO_CAMPAIGNS:
        campaign = repo.create_campaign(**spec)
        created.append(campaign)
        log(f"created campaign: {campaign['name']} ({campaign['region']}) -> {campaign['id']}")

    for campaign in created:
        for i in range(CYCLES_PER_CAMPAIGN):
            current = repo.get_campaign(campaign["id"])
            if current["status"] != "active":
                log(f"  [{campaign['name']}] cycle {i + 1}: skipped — campaign is {current['status']}")
                continue
            result = run_cycle(campaign["id"])
            think = result["think"]
            learn = result["learn"]
            if learn is None:
                note = " ".join(think.get("guardrail_notes") or []) or think["rationale"]
                log(
                    f"  [{campaign['name']}] cycle {result['cycle']}: "
                    f"{think['decision'].upper()} -> campaign paused. {note}"
                )
            else:
                log(
                    f"  [{campaign['name']}] cycle {result['cycle']}: "
                    f"{think['decision'].upper()} -> \"{think['headline']}\" "
                    f"| ctr={learn['ctr']:.3%} conv={learn['conversions']}"
                )

    return created
