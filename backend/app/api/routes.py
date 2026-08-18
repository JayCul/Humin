from __future__ import annotations

import base64

from fastapi import APIRouter, File, HTTPException, UploadFile

from app import scheduler
from app.agent.orchestrator import discard_draft, publish_draft, regenerate_draft, run_cycle
from app.config import get_settings
from app.db import mcp_client
from app.db.repository import get_repository
from app.models.schemas import Campaign, CampaignCreate, DraftDecision, DraftRegenerate, SchedulerStart
from app.seed_data import run_seed

router = APIRouter()

# Kept modest: the resulting base64 payload (~1.37x raw bytes) still has to
# fit comfortably inside a single Lambda Function URL response alongside the
# rest of a content-piece row, and inside CockroachDB's per-row practical
# limits without a second thought.
_MAX_IMAGE_BYTES = 4 * 1024 * 1024
_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/campaigns", response_model=Campaign)
def create_campaign(payload: CampaignCreate):
    repo = get_repository()
    return repo.create_campaign(**payload.model_dump())


@router.get("/campaigns")
def list_campaigns():
    repo = get_repository()
    return repo.get_campaigns()


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str):
    repo = get_repository()
    campaign = repo.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="campaign not found")
    return campaign


@router.post("/campaigns/{campaign_id}/run-cycle")
def trigger_cycle(campaign_id: str):
    repo = get_repository()
    campaign = repo.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="campaign not found")
    if campaign["status"] != "active":
        raise HTTPException(
            status_code=409,
            detail=f"campaign is {campaign['status']} - resume it before running another cycle",
        )
    if repo.get_pending_draft(campaign_id):
        raise HTTPException(
            status_code=409,
            detail="a draft is awaiting review - approve, edit, or discard it before running another cycle",
        )
    try:
        return run_cycle(campaign_id)
    except Exception as exc:  # surface a clean 500 with the real reason for demo debugging
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/campaigns/{campaign_id}/pending-draft")
def get_pending_draft(campaign_id: str):
    repo = get_repository()
    if not repo.get_campaign(campaign_id):
        raise HTTPException(status_code=404, detail="campaign not found")
    return repo.get_pending_draft(campaign_id)


@router.post("/campaigns/{campaign_id}/pending-draft/approve")
def approve_pending_draft(campaign_id: str, payload: DraftDecision | None = None):
    try:
        return publish_draft(
            campaign_id,
            headline=payload.headline if payload else None,
            body=payload.body if payload else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/pending-draft/discard")
def discard_pending_draft(campaign_id: str):
    try:
        return discard_draft(campaign_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/campaigns/{campaign_id}/pending-draft/regenerate")
def regenerate_pending_draft(campaign_id: str, payload: DraftRegenerate | None = None):
    try:
        return regenerate_draft(campaign_id, feedback=payload.feedback if payload else None)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/campaigns/{campaign_id}/content/{content_id}")
def get_content_piece(campaign_id: str, content_id: str):
    """Fetch one content piece, image included. Deliberately separate from
    /decisions - the image lives only here, never embedded into the audit
    trail (see content_pieces.image_data_url in schema.sql), so viewing a
    campaign's reasoning history never has to transfer N cycles' worth of
    images at once."""
    repo = get_repository()
    if not repo.get_campaign(campaign_id):
        raise HTTPException(status_code=404, detail="campaign not found")
    content = repo.get_content(campaign_id, content_id)
    if not content:
        raise HTTPException(status_code=404, detail="content not found")
    return content


@router.post("/campaigns/{campaign_id}/content/{content_id}/image")
async def upload_content_image(campaign_id: str, content_id: str, file: UploadFile = File(...)):
    """Attach a reviewer-supplied creative to a content piece (draft or
    already-published), replacing whatever image was there. Picked up as
    prior_ad_image the next time this campaign reasons, exactly like an
    AI-generated one - the agent doesn't distinguish the two when analyzing
    for a pivot."""
    repo = get_repository()
    if not repo.get_campaign(campaign_id):
        raise HTTPException(status_code=404, detail="campaign not found")
    content = repo.get_content(campaign_id, content_id)
    if not content:
        raise HTTPException(status_code=404, detail="content not found")
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported image type '{file.content_type}' - use PNG, JPEG, WebP, or GIF",
        )
    raw = await file.read()
    if len(raw) > _MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"image too large ({len(raw)} bytes) - max {_MAX_IMAGE_BYTES} bytes",
        )
    data_url = f"data:{file.content_type};base64,{base64.b64encode(raw).decode('ascii')}"
    updated = repo.update_content_image(content_id, image_data_url=data_url, image_source="uploaded", image_prompt=None)
    repo.log_decision(
        campaign_id=campaign_id,
        cycle=content["cycle"],
        phase="act",
        summary=f"Creative image replaced with an uploaded image for {content['channel']}.",
        detail={"content_id": content_id, "channel": content["channel"], "image_source": "uploaded"},
    )
    return updated


@router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str):
    repo = get_repository()
    if not repo.get_campaign(campaign_id):
        raise HTTPException(status_code=404, detail="campaign not found")
    return repo.update_campaign_status(campaign_id, "paused")


@router.post("/campaigns/{campaign_id}/resume")
def resume_campaign(campaign_id: str):
    repo = get_repository()
    if not repo.get_campaign(campaign_id):
        raise HTTPException(status_code=404, detail="campaign not found")
    return repo.update_campaign_status(campaign_id, "active")


@router.get("/campaigns/{campaign_id}/performance")
def get_performance(campaign_id: str):
    repo = get_repository()
    if not repo.get_campaign(campaign_id):
        raise HTTPException(status_code=404, detail="campaign not found")
    return repo.get_performance_history(campaign_id)


@router.get("/campaigns/{campaign_id}/decisions")
def get_decisions(campaign_id: str):
    repo = get_repository()
    if not repo.get_campaign(campaign_id):
        raise HTTPException(status_code=404, detail="campaign not found")
    return repo.get_decisions(campaign_id)


@router.get("/campaigns/{campaign_id}/trends")
def get_trends(campaign_id: str):
    repo = get_repository()
    if not repo.get_campaign(campaign_id):
        raise HTTPException(status_code=404, detail="campaign not found")
    return repo.get_recent_trend_signals(campaign_id, limit=10)


@router.get("/scheduler/status")
def scheduler_status():
    return scheduler.status()


@router.post("/scheduler/start")
def scheduler_start(payload: SchedulerStart | None = None):
    interval = payload.interval_seconds if payload else None
    return scheduler.start(interval)


@router.post("/scheduler/stop")
def scheduler_stop():
    return scheduler.stop()


@router.get("/system/status")
def system_status():
    """Live integration status for the Settings page - deliberately returns
    only booleans and public config (model IDs, region) derived from
    Settings, never the actual connection strings or API keys."""
    s = get_settings()
    mcp_tools = mcp_client.list_tools() if mcp_client.is_configured() else []
    return {
        "cockroachdb": {
            "mode": "live" if not s.use_mock_db else "mock",
            "url_configured": bool(s.cockroachdb_url),
            "mcp_configured": bool(s.cockroachdb_mcp_url),
            "mcp_tools": [t["name"] for t in mcp_tools],
        },
        "bedrock": {
            "mode": "live" if not s.use_mock_llm else "mock",
            "text_model_id": s.bedrock_text_model_id,
            "embedding_model_id": s.bedrock_embedding_model_id,
            "embedding_dimensions": s.embedding_dimensions,
            "aws_region": s.aws_region,
        },
        "trends": {
            "provider": s.trends_provider,
        },
        "scheduler": {
            "default_interval_seconds": s.scheduler_default_interval_seconds,
            **scheduler.status(),
        },
        "environment": s.environment,
    }


@router.post("/system/reset")
def system_reset():
    """Wipe every campaign and everything under it — the 'start fresh'
    control. Stops the in-app scheduler first so a mid-flight tick doesn't
    race the wipe."""
    scheduler.stop()
    repo = get_repository()
    repo.reset_all()
    return {"status": "reset", "campaigns": repo.get_campaigns()}


@router.post("/system/seed-demo")
def system_seed_demo():
    """Populate with the same demo campaigns + cycles as scripts/seed.py —
    the 'load demo data' control. Adds to whatever's already there rather
    than clearing first; call /system/reset beforehand for a clean slate."""
    repo = get_repository()
    log: list[str] = []
    created = run_seed(repo, log=log.append)
    return {"status": "seeded", "campaigns": created, "log": log}
