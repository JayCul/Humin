"""Pydantic request/response models for the API layer."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CampaignCreate(BaseModel):
    name: str
    product: str
    audience_segment: str
    goal: str = Field(description="'awareness' | 'conversion' | 'retention'")
    tone: str = "confident, plain-spoken"
    region: str = "us-east"
    budget_usd: float | None = Field(
        default=None, description="Total spend cap for this campaign. Omit/null for unlimited."
    )
    approval_mode: str = Field(
        default="autonomous",
        description="'autonomous' (publish immediately) | 'review' (draft awaits human approval before publishing)",
    )


class Campaign(BaseModel):
    id: str
    name: str
    product: str
    audience_segment: str
    goal: str
    tone: str
    status: str
    region: str
    budget_usd: float | None = None
    approval_mode: str = "autonomous"
    created_at: datetime


class DraftDecision(BaseModel):
    headline: str | None = None
    body: str | None = None


class DraftRegenerate(BaseModel):
    feedback: str | None = None


class SchedulerStart(BaseModel):
    interval_seconds: int | None = Field(
        default=None, description="Seconds between autonomous ticks. Omit to keep the current/default interval."
    )


class CycleResult(BaseModel):
    campaign_id: str
    cycle: int
    perceive: dict
    remember: list[dict]
    think: dict
    act: dict | None
    learn: dict | None
