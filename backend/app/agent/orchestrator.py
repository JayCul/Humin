"""The Humin agent loop: Perceive -> Remember -> Think -> Act -> Learn.

One call to `run_cycle(campaign_id)` is one full "day" for a campaign:
Huginn (Bedrock) reasons over what Muninn (CockroachDB memory) recalls, a new
content variant is written back into memory, and the ad-platform simulator
produces the outcome that becomes next cycle's input. Every phase is logged
to `agent_decisions` so the whole loop is auditable, not a black box.

Two things sit between the raw model output and what actually happens,
deliberately outside the LLM's control:

  * `_evidence_strength()` - a data-driven score (sample size, cycle count,
    memory-precedent quality) computed in code, not asked of the model.
    It's threaded into the prompt/mock context so Huginn can self-calibrate,
    and it's averaged into the final confidence score regardless of what the
    model claims - self-reported LLM confidence alone is not trustworthy
    enough to act on.
  * `_apply_guardrails()` - a hard downgrade, applied after the decision
    comes back, that prevents "kill" or a full pivot from ever being acted
    on when the evidence behind it is thin. This is enforced in code, not
    just requested in the prompt, because prompts are advisory and this
    isn't.
"""
from __future__ import annotations

import random
from typing import Any

from app.agent import bedrock_client
from app.db.repository import Repository, get_repository
from app.signals.trends_client import fetch_trend_signal
from app.simulator.ad_platform_sim import simulate_cycle, trend_label

_CHANNELS = ["email", "social", "search_ad", "display"]
_HISTORY_WINDOW = 5
_BOLD_MOVES = {"pivot_angle", "pivot_channel", "kill"}
_MIN_EVIDENCE_FOR_BOLD_MOVE = 0.35
_MIN_CYCLES_FOR_KILL = 3
_PIVOT_DECISIONS = {"pivot_angle", "pivot_channel"}
_BUDGET_CONSERVE_THRESHOLD = 0.85  # once this much of the budget is spent, stop starting new experiments
_STAGNATION_LIMIT = 3          # consecutive no-movement 'tweak' cycles before forcing a bigger move
_STAGNATION_CTR_TOLERANCE = 0.003  # CTR swing below this counts as "no real movement"


def _next_cycle(repo: Repository, campaign_id: str) -> int:
    history = repo.get_performance_history(campaign_id)
    if not history:
        return 1
    return max(h["cycle"] for h in history) + 1


def _own_history(
    repo: Repository, campaign_id: str, full_history: list[dict[str, Any]], limit: int = _HISTORY_WINDOW
) -> list[dict[str, Any]]:
    """The campaign's own last few cycles - what was tried and what
    happened - rather than a single collapsed trend label. This is what the
    reasoning step actually reads to judge its own trajectory. Takes the
    already-fetched full performance history rather than querying again."""
    perf = full_history[-limit:]
    think_by_cycle = {d["cycle"]: d for d in repo.get_decisions(campaign_id) if d["phase"] == "think"}

    history = []
    for p in perf:
        think = think_by_cycle.get(p["cycle"])
        detail = think["detail"] if think else {}
        history.append(
            {
                "cycle": p["cycle"],
                "headline": detail.get("headline"),
                "decision": detail.get("decision"),
                "impressions": p["impressions"],
                "clicks": p["clicks"],
                "conversions": p["conversions"],
                "ctr": float(p["ctr"]) if p.get("ctr") is not None else None,
                "spend_usd": float(p["spend_usd"]) if p.get("spend_usd") is not None else None,
            }
        )
    return history


def _memory_context(recalled: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach real outcomes to recalled precedent - a recalled headline with
    no known result is much weaker evidence than one with a proven CTR."""
    out = []
    for r in recalled:
        entry = {
            "campaign_name": r["campaign_name"],
            "region": r["region"],
            "headline": r["headline"],
            "channel": r.get("channel"),
            "similarity": round(1 - float(r["distance"]), 4),
        }
        if r.get("ctr") is not None:
            entry["outcome"] = {
                "ctr": float(r["ctr"]),
                "conversions": r.get("conversions"),
                "spend_usd": float(r["spend_usd"]) if r.get("spend_usd") is not None else None,
            }
        else:
            entry["outcome"] = None
        out.append(entry)
    return out


def _evidence_strength(recent_cycles: list[dict[str, Any]], recalled_memory: list[dict[str, Any]]) -> float:
    """How much this decision should actually be trusted, computed from data
    rather than asked of the model. Cold start (no history, no precedent)
    scores low on purpose - early cycles should be cautious by construction,
    not because the model happened to say so."""
    if not recent_cycles:
        return 0.15

    total_impressions = sum(c.get("impressions", 0) or 0 for c in recent_cycles)
    impressions_score = min(0.35, (total_impressions / 20_000) * 0.35)
    cycles_score = min(0.25, len(recent_cycles) * 0.06)

    memory_with_outcome = [r for r in recalled_memory if r.get("outcome")]
    if memory_with_outcome:
        avg_similarity = sum(r["similarity"] for r in memory_with_outcome) / len(memory_with_outcome)
    else:
        avg_similarity = 0.0
    memory_score = min(0.25, avg_similarity * 0.25)

    return round(min(0.95, 0.15 + impressions_score + cycles_score + memory_score), 3)


def _apply_guardrails(decision: str, evidence_strength: float, cycles_observed: int) -> tuple[str, list[str]]:
    """Enforced in code, not just requested in the prompt: bold moves get
    capped back down to 'tweak' when the evidence behind them is thin."""
    notes: list[str] = []

    if decision in _BOLD_MOVES and evidence_strength < _MIN_EVIDENCE_FOR_BOLD_MOVE:
        notes.append(
            f"Downgraded from '{decision}' to 'tweak': evidence strength is only "
            f"{evidence_strength:.2f} - not enough signal yet to justify a bigger move."
        )
        decision = "tweak"

    if decision == "kill" and cycles_observed < _MIN_CYCLES_FOR_KILL:
        notes.append(
            f"Downgraded from 'kill' to 'tweak': only {cycles_observed} cycle(s) observed - "
            f"need at least {_MIN_CYCLES_FOR_KILL} before recommending a stop."
        )
        decision = "tweak"

    return decision, notes


def _is_stagnant(own_history: list[dict[str, Any]]) -> bool:
    """True when the last _STAGNATION_LIMIT cycles were all 'tweak' decisions
    with no meaningful CTR movement between any of them - small edits that
    aren't going anywhere. Plain decline/improve trend logic reads this
    situation as simply "flat" and never escalates on its own, which means a
    campaign that's chronically mediocre (as opposed to declining, or
    catastrophically bad) could get tweaked forever instead of ever trying a
    genuinely different angle or channel. This check exists specifically to
    close that gap."""
    if len(own_history) < _STAGNATION_LIMIT:
        return False
    window = own_history[-_STAGNATION_LIMIT:]
    if not all(c.get("decision") == "tweak" for c in window):
        return False
    for prev, curr in zip(window, window[1:]):
        if prev.get("ctr") is None or curr.get("ctr") is None:
            continue
        if abs(curr["ctr"] - prev["ctr"]) > _STAGNATION_CTR_TOLERANCE:
            return False  # something did move meaningfully - not a true plateau
    return True


def _apply_plateau_escalation(decision: str, own_history: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Runs before the evidence/budget guardrails below, on the raw
    model/mock decision - so a stagnation-triggered escalation is still
    subject to the same caution those guardrails enforce, rather than
    bypassing them."""
    notes: list[str] = []
    if decision == "tweak" and _is_stagnant(own_history):
        notes.append(
            f"Escalated from 'tweak' to 'pivot_channel': {_STAGNATION_LIMIT} straight cycles of small "
            f"edits with no real CTR movement - time to try something genuinely different, not another tweak."
        )
        decision = "pivot_channel"
    return decision, notes


def _apply_budget_guardrail(
    decision: str, total_spend: float, budget_usd: float | None
) -> tuple[str, list[str]]:
    """A financial guardrail, separate from the evidence guardrail above and
    enforced the same way: in code, after the model/mock has already made
    its call, not just requested in the prompt. `budget_usd` is opt-in per
    campaign - campaigns without one are treated as unconstrained."""
    notes: list[str] = []
    if budget_usd is None or budget_usd <= 0:
        return decision, notes

    remaining = budget_usd - total_spend
    if remaining <= 0:
        if decision != "kill":
            notes.append(
                f"Forced to 'kill': budget exhausted (${total_spend:.2f} of ${budget_usd:.2f} spent)."
            )
        return "kill", notes

    if remaining <= (1 - _BUDGET_CONSERVE_THRESHOLD) * budget_usd and decision in _PIVOT_DECISIONS:
        notes.append(
            f"Downgraded from '{decision}' to 'tweak': only ${remaining:.2f} of ${budget_usd:.2f} "
            f"budget left - conserving spend instead of starting a bigger experiment."
        )
        decision = "tweak"

    return decision, notes


def _run_reasoning(
    repo: Repository, campaign: dict[str, Any], cycle: int, human_feedback: str | None = None
) -> dict[str, Any]:
    """Perceive -> Remember -> Think, as one bundle. Used by `run_cycle` for
    a fresh cycle and by `regenerate_draft` for a re-draft of an *existing*
    cycle (same cycle number, with a reviewer's feedback folded into Think) -
    so a regenerated draft goes through the exact same reasoning path, not a
    lighter-weight one."""
    campaign_id = campaign["id"]

    # ---- PERCEIVE ---------------------------------------------------
    full_history = repo.get_performance_history(campaign_id)
    own_history = _own_history(repo, campaign_id, full_history)
    perf_trend = trend_label(full_history)
    baseline_ctr = (
        float(full_history[0]["ctr"]) if full_history and full_history[0].get("ctr") is not None else None
    )
    trend = fetch_trend_signal(product=campaign["product"], audience_segment=campaign["audience_segment"], cycle=cycle)
    repo.add_trend_signal(campaign_id=campaign_id, topic=trend["topic"], source=trend["source"], score=trend["score"])
    repo.log_decision(
        campaign_id=campaign_id,
        cycle=cycle,
        phase="perceive",
        summary=(
            f"Reviewed {len(own_history)} prior cycle(s) (trend: {perf_trend}); "
            f"live signal '{trend['topic']}' scoring {trend['score']:.2f} from {trend['source']}."
        ),
        detail={"performance_trend": perf_trend, "recent_cycles": own_history, "trend": trend},
    )

    # ---- REMEMBER (Muninn / CockroachDB vector recall) ---------------
    recall_query_text = (
        f"{campaign['product']} campaign for {campaign['audience_segment']}, "
        f"goal={campaign['goal']}, current trend={trend['topic']}, performance={perf_trend}"
    )
    query_embedding = bedrock_client.embed_text(recall_query_text)
    recalled = repo.search_similar_content(query_embedding, exclude_campaign_id=campaign_id, limit=3)
    memory_summaries = _memory_context(recalled)
    with_outcome = sum(1 for m in memory_summaries if m["outcome"])
    repo.log_decision(
        campaign_id=campaign_id,
        cycle=cycle,
        phase="remember",
        summary=(
            f"Recalled {len(memory_summaries)} similar ad(s) from CockroachDB's distributed "
            f"vector index ({with_outcome} with a known outcome to compare against)."
            if memory_summaries
            else "No prior precedent found in memory yet - this is effectively cold-start."
        ),
        detail={"query": recall_query_text, "recalled": memory_summaries},
    )

    # ---- THINK (Huginn / Bedrock) -------------------------------------
    evidence_strength = _evidence_strength(own_history, memory_summaries)
    budget_usd_for_context = campaign.get("budget_usd")
    # The actual creative from the most recent PUBLISHED cycle (not the
    # draft being reasoned about right now) - sent to Bedrock as a real
    # vision input so a pivot decision can weigh the image, not just copy.
    prior_content = repo.get_latest_content(campaign_id)
    prior_image_data_url = prior_content.get("image_data_url") if prior_content else None
    strategy_context = {
        "product": campaign["product"],
        "audience_segment": campaign["audience_segment"],
        "goal": campaign["goal"],
        "tone": campaign["tone"],
        "recent_cycles": own_history,
        "performance_trend_label": perf_trend,
        "recalled_memory": memory_summaries,
        "trend_topic": trend["topic"],
        "trend_score": trend["score"],
        "evidence_strength": evidence_strength,
        "budget_usd": float(budget_usd_for_context) if budget_usd_for_context is not None else None,
        "baseline_ctr": baseline_ctr,
        "human_feedback": human_feedback,
        "prior_image_data_url": prior_image_data_url,
    }
    raw_strategy = bedrock_client.generate_strategy(strategy_context)

    # Plateau escalation runs first, on the raw decision - a stagnation-driven
    # bump to 'pivot_channel' is still subject to the evidence/budget caution
    # below, not a way around it.
    decision, plateau_notes = _apply_plateau_escalation(raw_strategy["decision"], own_history)
    decision, evidence_notes = _apply_guardrails(decision, evidence_strength, cycles_observed=len(own_history))
    # Budget must be summed over ALL cycles, not just the _HISTORY_WINDOW-limited
    # `own_history` used for reasoning context - a campaign past cycle 5 would
    # otherwise silently undercount spend against its cap.
    total_spend_so_far = sum(float(h.get("spend_usd") or 0) for h in full_history)
    budget_usd = campaign.get("budget_usd")
    decision, budget_notes = _apply_budget_guardrail(
        decision, total_spend_so_far, float(budget_usd) if budget_usd is not None else None
    )
    guardrail_notes = plateau_notes + evidence_notes + budget_notes
    # Structured categories, not just prose - so a page aggregating across
    # every cycle in the fleet (Insights) can count "how often did each
    # guardrail actually fire" without parsing sentences.
    guardrail_categories = []
    if plateau_notes:
        guardrail_categories.append("plateau")
    if evidence_notes:
        guardrail_categories.append("evidence")
    if budget_notes:
        guardrail_categories.append("budget")

    model_confidence = float(raw_strategy.get("confidence", 0.5))
    final_confidence = round((model_confidence + evidence_strength) / 2, 3)

    strategy = {
        **raw_strategy,
        "decision": decision,
        "confidence": final_confidence,
        "confidence_breakdown": {
            "model_self_reported": model_confidence,
            "evidence_strength": evidence_strength,
            "final": final_confidence,
        },
        "guardrail_notes": guardrail_notes,
        "guardrail_categories": guardrail_categories,
    }

    think_summary = f"Decision: {decision.upper()} (confidence {final_confidence:.0%}) - {strategy['rationale']}"
    if human_feedback:
        think_summary += f" [redrafted per reviewer feedback: \"{human_feedback}\"]"
    if guardrail_notes:
        think_summary += " " + " ".join(guardrail_notes)

    repo.log_decision(
        campaign_id=campaign_id,
        cycle=cycle,
        phase="think",
        summary=think_summary,
        detail=strategy,
    )

    return {
        "perf_trend": perf_trend,
        "trend": trend,
        "own_history": own_history,
        "memory_summaries": memory_summaries,
        "strategy": strategy,
        "decision": decision,
        "final_confidence": final_confidence,
    }


def run_cycle(campaign_id: str) -> dict[str, Any]:
    repo = get_repository()
    campaign = repo.get_campaign(campaign_id)
    if not campaign:
        raise ValueError(f"campaign {campaign_id} not found")
    if campaign["status"] != "active":
        raise ValueError(
            f"campaign {campaign_id} is {campaign['status']}, not active - resume it before running another cycle"
        )
    if repo.get_pending_draft(campaign_id):
        raise ValueError(
            f"campaign {campaign_id} has a draft awaiting review - approve, edit, or discard it "
            "before running another cycle"
        )

    cycle = _next_cycle(repo, campaign_id)
    rng = random.Random(f"{campaign_id}:{cycle}")

    reasoning = _run_reasoning(repo, campaign, cycle)
    perf_trend, trend = reasoning["perf_trend"], reasoning["trend"]
    own_history, memory_summaries = reasoning["own_history"], reasoning["memory_summaries"]
    strategy, decision, final_confidence = reasoning["strategy"], reasoning["decision"], reasoning["final_confidence"]

    # ---- ACT -------------------------------------------------------------
    if decision == "kill":
        repo.update_campaign_status(campaign_id, "paused")
        repo.log_decision(
            campaign_id=campaign_id,
            cycle=cycle,
            phase="act",
            summary="Ad campaign paused - agent recommended killing this direction. No new ad shipped.",
            detail={"paused": True},
        )
        repo.log_decision(
            campaign_id=campaign_id,
            cycle=cycle,
            phase="learn",
            summary="No outcome to record - campaign paused before shipping a new ad.",
            detail={"paused": True},
        )
        return {
            "campaign_id": campaign_id,
            "cycle": cycle,
            "perceive": {"performance_trend": perf_trend, "trend": trend},
            "remember": memory_summaries,
            "think": strategy,
            "act": {"content": None, "channel": None, "paused": True},
            "learn": None,
        }

    channel = _CHANNELS[cycle % len(_CHANNELS)]
    content_text = f"{strategy['headline']}\n{strategy['body']}"
    content_embedding = bedrock_client.embed_text(content_text)
    image_prompt = strategy.get("image_prompt") or f"{campaign['product']} ad creative for {campaign['audience_segment']}"
    image_data_url = bedrock_client.generate_image(image_prompt)

    if campaign.get("approval_mode") == "review":
        # Human-in-the-loop: stop here. The draft is real (embedded, in the
        # table) but excluded from memory recall until a reviewer approves,
        # edits-then-approves, or discards it via publish_draft/discard_draft
        # below — Learn doesn't run yet either, since nothing's actually
        # live to have an outcome.
        content = repo.add_content_piece(
            campaign_id=campaign_id,
            cycle=cycle,
            version=1,
            channel=channel,
            headline=strategy["headline"],
            body=strategy["body"],
            embedding=content_embedding,
            generated_by_decision_id=None,
            status="draft",
            image_data_url=image_data_url,
            image_source="generated" if image_data_url else None,
            image_prompt=image_prompt,
        )
        repo.log_decision(
            campaign_id=campaign_id,
            cycle=cycle,
            phase="act",
            summary=f"Drafted new {channel} ad, awaiting review: “{strategy['headline']}”",
            detail={"content_id": content["id"], "channel": channel, "status": "draft"},
        )
        return {
            "campaign_id": campaign_id,
            "cycle": cycle,
            "perceive": {"performance_trend": perf_trend, "trend": trend},
            "remember": memory_summaries,
            "think": strategy,
            "act": {"content": content, "channel": channel, "status": "draft", "awaiting_review": True},
            "learn": None,
        }

    content = repo.add_content_piece(
        campaign_id=campaign_id,
        cycle=cycle,
        version=1,
        channel=channel,
        headline=strategy["headline"],
        body=strategy["body"],
        embedding=content_embedding,
        generated_by_decision_id=None,
        image_data_url=image_data_url,
        image_source="generated" if image_data_url else None,
        image_prompt=image_prompt,
    )
    repo.log_decision(
        campaign_id=campaign_id,
        cycle=cycle,
        phase="act",
        summary=f"Published new {channel} ad: “{strategy['headline']}”",
        detail={"content_id": content["id"], "channel": channel},
    )

    # ---- LEARN (simulate outcome, closes the loop) ---------------------
    prior_ctr = own_history[-1]["ctr"] if own_history else None
    outcome = simulate_cycle(
        decision=decision,
        confidence=final_confidence,
        trend_score=float(trend["score"]),
        prior_ctr=prior_ctr,
        rng=rng,
    )
    performance = repo.record_performance(
        content_id=content["id"],
        campaign_id=campaign_id,
        cycle=cycle,
        **outcome,
    )
    repo.log_decision(
        campaign_id=campaign_id,
        cycle=cycle,
        phase="learn",
        summary=(
            f"Simulated outcome: {outcome['ctr']:.3%} CTR, {outcome['conversions']} conversions "
            f"on ${outcome['spend_usd']:.2f} spend. This becomes memory for the next cycle."
        ),
        detail=outcome,
    )

    return {
        "campaign_id": campaign_id,
        "cycle": cycle,
        "perceive": {"performance_trend": perf_trend, "trend": trend},
        "remember": memory_summaries,
        "think": strategy,
        "act": {"content": content, "channel": channel},
        "learn": performance,
    }


def _find_decision(decisions: list[dict[str, Any]], cycle: int, phase: str) -> dict[str, Any] | None:
    matches = [d for d in decisions if d["cycle"] == cycle and d["phase"] == phase]
    return matches[-1] if matches else None


def publish_draft(campaign_id: str, headline: str | None = None, body: str | None = None) -> dict[str, Any]:
    """Approve a pending draft — as drafted, or with a reviewer's edits — and
    complete the cycle: re-embeds if the text actually changed (so memory
    reflects what really went out, not the AI's first pass), publishes it,
    then runs Learn to close the loop exactly like an autonomous cycle does."""
    repo = get_repository()
    draft = repo.get_pending_draft(campaign_id)
    if not draft:
        raise ValueError(f"campaign {campaign_id} has no draft awaiting review")

    cycle = draft["cycle"]
    final_headline = headline if headline is not None else draft["headline"]
    final_body = body if body is not None else draft["body"]
    edited = final_headline != draft["headline"] or final_body != draft["body"]

    if edited:
        new_embedding = bedrock_client.embed_text(f"{final_headline}\n{final_body}")
        content = repo.update_content_status(
            draft["id"], "published", headline=final_headline, body=final_body, embedding=new_embedding
        )
    else:
        content = repo.update_content_status(draft["id"], "published")

    repo.log_decision(
        campaign_id=campaign_id,
        cycle=cycle,
        phase="act",
        summary=f"Published {'with reviewer edits' if edited else 'as drafted'}: “{final_headline}”",
        detail={
            "content_id": content["id"],
            "channel": content["channel"],
            "edited": edited,
            "headline": final_headline,
            "body": final_body,
        },
    )

    # ---- LEARN — pull the decision/confidence/trend this draft was made
    # with (logged at draft time) rather than recomputing; the review could
    # have taken a while and nothing about the campaign's own state should
    # silently drift out from under the decision a human just approved.
    decisions = repo.get_decisions(campaign_id)
    think = _find_decision(decisions, cycle, "think")
    perceive = _find_decision(decisions, cycle, "perceive")
    strategy = think["detail"] if think else {}
    trend = perceive["detail"]["trend"] if perceive else {"score": 0.0}
    decision = strategy.get("decision", "keep")
    final_confidence = float(strategy.get("confidence", 0.5))

    full_history = repo.get_performance_history(campaign_id)
    prior_ctr = float(full_history[-1]["ctr"]) if full_history and full_history[-1].get("ctr") is not None else None
    rng = random.Random(f"{campaign_id}:{cycle}")
    outcome = simulate_cycle(
        decision=decision, confidence=final_confidence, trend_score=float(trend.get("score", 0.0)),
        prior_ctr=prior_ctr, rng=rng,
    )
    performance = repo.record_performance(content_id=content["id"], campaign_id=campaign_id, cycle=cycle, **outcome)
    repo.log_decision(
        campaign_id=campaign_id,
        cycle=cycle,
        phase="learn",
        summary=(
            f"Simulated outcome: {outcome['ctr']:.3%} CTR, {outcome['conversions']} conversions "
            f"on ${outcome['spend_usd']:.2f} spend. This becomes memory for the next cycle."
        ),
        detail=outcome,
    )

    return {
        "campaign_id": campaign_id,
        "cycle": cycle,
        "think": strategy,
        "act": {"content": content, "channel": content["channel"], "edited": edited},
        "learn": performance,
    }


def discard_draft(campaign_id: str) -> dict[str, Any]:
    """Reject a draft outright — no content published this cycle. The
    campaign stays active; the next call to run_cycle starts a fresh one."""
    repo = get_repository()
    draft = repo.get_pending_draft(campaign_id)
    if not draft:
        raise ValueError(f"campaign {campaign_id} has no draft awaiting review")

    content = repo.update_content_status(draft["id"], "discarded")
    repo.log_decision(
        campaign_id=campaign_id,
        cycle=draft["cycle"],
        phase="act",
        summary=f"Draft discarded by reviewer — no ad published this cycle: “{draft['headline']}”",
        detail={"content_id": content["id"], "status": "discarded"},
    )
    repo.log_decision(
        campaign_id=campaign_id,
        cycle=draft["cycle"],
        phase="learn",
        summary="No outcome to record — draft discarded before publishing.",
        detail={"discarded": True},
    )
    return {"campaign_id": campaign_id, "cycle": draft["cycle"], "status": "discarded"}


def regenerate_draft(campaign_id: str, feedback: str | None = None) -> dict[str, Any]:
    """Discard the current draft (kept, marked 'discarded', for audit) and
    run Think again for the *same* cycle, this time with the reviewer's
    feedback folded into the reasoning — a real redraft, not a cosmetic
    retry."""
    repo = get_repository()
    campaign = repo.get_campaign(campaign_id)
    if not campaign:
        raise ValueError(f"campaign {campaign_id} not found")
    draft = repo.get_pending_draft(campaign_id)
    if not draft:
        raise ValueError(f"campaign {campaign_id} has no draft awaiting review")

    cycle = draft["cycle"]
    repo.update_content_status(draft["id"], "discarded")

    reasoning = _run_reasoning(repo, campaign, cycle, human_feedback=feedback)
    strategy = reasoning["strategy"]
    channel = _CHANNELS[cycle % len(_CHANNELS)]
    content_embedding = bedrock_client.embed_text(f"{strategy['headline']}\n{strategy['body']}")
    image_prompt = strategy.get("image_prompt") or f"{campaign['product']} ad creative for {campaign['audience_segment']}"
    image_data_url = bedrock_client.generate_image(image_prompt)
    content = repo.add_content_piece(
        campaign_id=campaign_id,
        cycle=cycle,
        version=draft["version"] + 1,
        channel=channel,
        headline=strategy["headline"],
        body=strategy["body"],
        embedding=content_embedding,
        generated_by_decision_id=None,
        status="draft",
        image_data_url=image_data_url,
        image_source="generated" if image_data_url else None,
        image_prompt=image_prompt,
    )
    repo.log_decision(
        campaign_id=campaign_id,
        cycle=cycle,
        phase="act",
        summary=f"Redrafted new {channel} ad, awaiting review: “{strategy['headline']}”",
        detail={"content_id": content["id"], "channel": channel, "status": "draft", "feedback": feedback},
    )

    return {
        "campaign_id": campaign_id,
        "cycle": cycle,
        "perceive": {"trend": reasoning["trend"]},
        "remember": reasoning["memory_summaries"],
        "think": strategy,
        "act": {"content": content, "channel": channel, "status": "draft", "awaiting_review": True},
        "learn": None,
    }


def run_all_active_campaigns() -> dict[str, Any]:
    """Run one cycle for every active campaign. This is the one function
    both the AWS Lambda handler (`infra/lambda/handler.py`, triggered by an
    EventBridge schedule for the real deployment) and the in-app scheduler
    (`app/scheduler.py`, used for live demos without needing AWS credentials
    wired up) call - so scheduled behaviour is identical no matter which
    trigger fired it. One campaign failing (e.g. a transient Bedrock error)
    doesn't block the rest from running. Campaigns sitting on an unreviewed
    draft are skipped — starting another cycle on top of one would be lost
    work at best and two competing drafts at worst."""
    repo = get_repository()
    campaigns = [c for c in repo.get_campaigns() if c.get("status") == "active"]

    ran = []
    errors = []
    skipped = []
    for campaign in campaigns:
        if repo.get_pending_draft(campaign["id"]):
            skipped.append({"campaign_id": campaign["id"], "reason": "awaiting review"})
            continue
        try:
            result = run_cycle(campaign["id"])
            ran.append({"campaign_id": campaign["id"], "cycle": result["cycle"], "decision": result["think"]["decision"]})
        except Exception as exc:  # noqa: BLE001 - one campaign's failure must not sink the batch
            errors.append({"campaign_id": campaign["id"], "error": str(exc)})

    return {"ran": ran, "errors": errors, "skipped": skipped}
