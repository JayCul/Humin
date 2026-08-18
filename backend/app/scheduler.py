"""In-app scheduler - the demo-friendly path to "autonomous."

The real, production-shaped path to scheduled autonomy is AWS Lambda on an
EventBridge cadence (see `infra/lambda/handler.py` + `infra/README.md`) - that's what the actual hackathon submission is built around, and it's what
you'd run in production. But requiring a deployed AWS stack just to *show*
the loop running on its own, live, in front of judges, is a fragile demo
dependency. This module gives the dashboard a real "Enable autonomous mode"
switch that ticks on an interval and calls the exact same
`orchestrator.run_all_active_campaigns()` the Lambda handler calls - so
what you see in the live demo is genuinely the same code path, just
triggered locally instead of by EventBridge.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from app.agent.orchestrator import run_all_active_campaigns
from app.config import get_settings

logger = logging.getLogger("humin.scheduler")

_JOB_ID = "humin-autonomous-loop"

_lock = threading.Lock()
_scheduler: BackgroundScheduler | None = None
_state: dict[str, Any] = {
    "enabled": False,
    "interval_seconds": None,
    "last_run_at": None,
    "last_run_summary": None,
}


def _tick() -> None:
    outcome = run_all_active_campaigns()
    with _lock:
        _state["last_run_at"] = datetime.now(timezone.utc).isoformat()
        _state["last_run_summary"] = {"ran": len(outcome["ran"]), "errors": len(outcome["errors"])}
    logger.info("scheduler tick: ran %d campaign(s), %d error(s)", len(outcome["ran"]), len(outcome["errors"]))


def start(interval_seconds: int | None = None) -> dict[str, Any]:
    global _scheduler
    with _lock:
        interval = interval_seconds or _state["interval_seconds"] or get_settings().scheduler_default_interval_seconds
        _state["interval_seconds"] = interval
        if _scheduler is None:
            _scheduler = BackgroundScheduler()
            _scheduler.start()
        if _scheduler.get_job(_JOB_ID):
            _scheduler.remove_job(_JOB_ID)
        # Fire immediately on enable, then repeat every `interval` seconds - # so flipping the switch shows a result right away, not after a wait.
        _scheduler.add_job(
            _tick, "interval", seconds=interval, id=_JOB_ID, next_run_time=datetime.now(timezone.utc)
        )
        _state["enabled"] = True
    return status()


def stop() -> dict[str, Any]:
    with _lock:
        if _scheduler and _scheduler.get_job(_JOB_ID):
            _scheduler.remove_job(_JOB_ID)
        _state["enabled"] = False
    return status()


def status() -> dict[str, Any]:
    with _lock:
        next_run_at = None
        if _scheduler and _state["enabled"]:
            job = _scheduler.get_job(_JOB_ID)
            if job and job.next_run_time:
                next_run_at = job.next_run_time.isoformat()
        return {
            "enabled": _state["enabled"],
            "interval_seconds": _state["interval_seconds"] or get_settings().scheduler_default_interval_seconds,
            "last_run_at": _state["last_run_at"],
            "last_run_summary": _state["last_run_summary"],
            "next_run_at": next_run_at,
        }
