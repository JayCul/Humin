"""AWS Lambda entry point: run one agent cycle for every active campaign.

Intended to be triggered on a schedule (EventBridge rule, e.g. every hour)
so campaigns keep adapting without the FastAPI dashboard needing to be the
thing driving cycles - the dashboard's "Run next cycle" button and this
handler both call the same `run_cycle()`, so behaviour is identical whether
a human or a schedule triggers it.

Package for deployment:
    cd backend
    pip install -r requirements.txt -t build/
    cp -r app build/
    cp ../infra/lambda/handler.py build/
    cd build && zip -r ../humin-lambda.zip . && cd ..

Lambda configuration:
    Runtime: Python 3.12
    Handler: handler.run_all_active_campaigns
    Env vars: same as backend/.env.example (COCKROACHDB_URL, AWS Bedrock
              model IDs, USE_MOCK_LLM=false, USE_MOCK_DB=false, ...)
    Execution role: needs bedrock:InvokeModel on the configured model IDs;
                    outbound network access to the CockroachDB Cloud cluster
                    (VPC + NAT, or CockroachDB Cloud's public endpoint with
                    the role's egress allowed).
    Trigger: EventBridge Scheduler rule, e.g. rate(1 hour)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.agent.orchestrator import run_all_active_campaigns as _run_all_active_campaigns
from app.agent.orchestrator import run_cycle

logger = logging.getLogger("humin.lambda")
logging.basicConfig(level=logging.INFO)


def run_all_active_campaigns(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point - thin wrapper around the shared
    `orchestrator.run_all_active_campaigns()` so the EventBridge-triggered
    path and the in-app demo scheduler (`app/scheduler.py`) run exactly the
    same logic, just from different triggers."""
    outcome = _run_all_active_campaigns()
    for r in outcome["ran"]:
        logger.info("ran cycle %s for campaign %s (%s)", r["cycle"], r["campaign_id"], r["decision"])
    for e in outcome["errors"]:
        logger.error("cycle failed for campaign %s: %s", e["campaign_id"], e["error"])

    return {
        "statusCode": 200 if not outcome["errors"] else 207,
        "body": json.dumps(outcome),
    }


def run_single_campaign(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Alternative handler for an EventBridge rule or API Gateway integration
    that targets one campaign, e.g. event = {"campaign_id": "..."}."""
    campaign_id = event.get("campaign_id")
    if not campaign_id:
        return {"statusCode": 400, "body": json.dumps({"error": "campaign_id is required"})}
    try:
        result = run_cycle(campaign_id)
        return {"statusCode": 200, "body": json.dumps(result, default=str)}
    except Exception as exc:
        logger.exception("cycle failed for campaign %s", campaign_id)
        return {"statusCode": 500, "body": json.dumps({"error": str(exc)})}
