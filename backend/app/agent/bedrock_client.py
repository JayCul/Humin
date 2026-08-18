"""Amazon Bedrock client - Humin's "Huginn" (Thought).

Two capabilities:
  * `generate_strategy()` - Claude on Bedrock reasons over this campaign's
                              own recent cycles, precedent recalled from
                              memory (with real outcomes attached), and a
                              trend signal. Returns a structured decision - not just "keep or pivot" but which of five
                              real ad-campaign moves to make - plus a named
                              breakdown of *why*.
  * `embed_text()` - Titan Embed Text v2 on Bedrock turns ad copy
                              into a vector Humin can later recall by meaning,
                              not keyword, via CockroachDB's vector index.
  * `generate_image()` - Titan Image Generator on Bedrock renders the actual
                              creative (not just copy) from the visual
                              direction Huginn wrote alongside the headline/
                              body. The *previous* cycle's image is fed back
                              into the next `generate_strategy()` call as a
                              real vision input - Huginn looks at its own
                              prior creative, not just its own prior text,
                              when deciding whether to pivot.

Both fall back to deterministic mock behaviour when `USE_MOCK_LLM=true` or
when boto3/credentials aren't available. The mock path is not a stub - it
runs the same kind of conditional reasoning over the same inputs a real LLM
would see, so the agent's behaviour is legible and testable offline, not
just "plausible-looking."
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from typing import Any

from app.config import get_settings

logger = logging.getLogger("humin.bedrock")

DECISIONS = ("keep", "tweak", "pivot_angle", "pivot_channel", "kill")

_STRATEGY_SYSTEM_PROMPT = """You are Huginn, the reasoning half of an autonomous ad manager.

You are given:
  - recent_cycles: this campaign's own last few attempts and what happened to
    each one (headline, decision made, CTR, conversions).
  - recalled_memory: ad copy recalled from OTHER campaigns/regions because it
    was semantically similar to the current situation - each item includes
    its actual outcome (CTR/conversions) if one exists yet.
  - trend_topic / trend_score: a live external signal (0-1).
  - evidence_strength (0-1): how much real data backs this decision. Treat
    this as a hard ceiling on how aggressive you're allowed to be - do not
    recommend "kill" or a pivot on thin evidence, no matter how tempting the
    numbers look.
  - baseline_ctr: this specific campaign's own first-cycle CTR, or null if
    none exists yet. Judge "failing" relative to THIS number, not a generic
    benchmark - a B2B agricultural campaign and a consumer retail campaign
    have no business being held to the same absolute CTR expectation.
  - human_feedback: optional. A human reviewer rejected the previous draft
    for this exact cycle and left a note on what to change (e.g. "make it
    punchier", "drop the pricing mention", "wrong tone for this audience").
    When present, this is a direct instruction for the headline/body you
    draft this time — treat it as higher priority than your own stylistic
    instincts, and make the change concrete and visible, not token. It does
    not override the decision logic above (keep/tweak/pivot/kill still
    follows the evidence) — it's about the *ad copy*, not the strategy.
  - prior_ad_image: optional. The actual creative image published in this
    campaign's most recent cycle, attached below as an image, not just
    described. Look at it - composition, subject, color, mood, apparent
    polish - the same way you read recent_cycles' numbers. A pivot can be
    visual as much as verbal: stale or generic creative is itself a reason to
    pivot_angle even when the copy still reads fine, and a genuinely strong
    image is a reason to keep iterating on the same visual direction rather
    than throwing it away for a new one.

Choose exactly one decision:
  - "keep"          current angle is working - ship a close variant to keep testing it
  - "tweak"          small copy/framing change, same core angle and channel
  - "pivot_angle"    change the core message/positioning, same channel
  - "pivot_channel"  same message, different channel
  - "kill"           recommend stopping this campaign direction entirely - only
                     with strong, sustained evidence across several cycles

Respond ONLY with JSON matching this shape:
{
  "decision": "keep" | "tweak" | "pivot_angle" | "pivot_channel" | "kill",
  "performance_assessment": "1-2 sentences on what recent_cycles show, citing actual numbers",
  "memory_assessment": "1-2 sentences on what recalled_memory shows - cite a specific recalled outcome if one exists, or say plainly there's no precedent yet",
  "trend_assessment": "1 sentence on whether the trend signal is actually relevant here or should be treated as noise",
  "rationale": "1-2 sentence synthesis explaining the final call",
  "headline": "new headline, <= 12 words",
  "body": "new body copy, 2-4 sentences",
  "image_prompt": "visual direction for an image-generation model to render this ad's creative: subject, setting, style, mood - concrete and specific, no on-image text/words/logos since text-to-image models render text poorly",
  "confidence": 0.0-1.0
}"""


def _mock_embedding(text: str, dims: int) -> list[float]:
    """Deterministic pseudo-embedding using the classic hashing-trick
    bag-of-words: each word hashes to a dimension and a sign, so texts that
    share vocabulary end up genuinely closer in cosine distance - unlike a
    pure hash-of-the-whole-string vector, which is uncorrelated noise no
    matter how similar the inputs are. Not a real embedding model, but it
    means the offline 'remember' phase behaves like semantic recall instead
    of random noise, so mock mode actually exercises the same retrieval
    logic (including 'pivot_angle', which depends on finding a genuinely
    similar high-performing precedent) that the real Bedrock path would."""
    vec = [0.0] * dims
    words = re.findall(r"[a-z0-9]+", text.lower())
    if not words:
        return vec
    for word in words:
        idx = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16) % dims
        sign = 1.0 if int(hashlib.sha256((word + ":sign").encode("utf-8")).hexdigest(), 16) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def _apply_feedback(headline: str, body: str, feedback: str | None) -> tuple[str, str]:
    """Mock mode has no real language model to actually rewrite copy against
    a note — but it should still visibly *do something* with the feedback
    rather than silently ignore it, so the mechanism is demoable offline
    too. Real Bedrock gets the same feedback as a direct prompt instruction
    instead (see _STRATEGY_SYSTEM_PROMPT) and will genuinely rewrite."""
    if not feedback:
        return headline, body
    return headline, f"{body} (Adjusted per your note: \"{feedback}\".)"


def _draft_copy(
    decision: str, product: str, audience: str, trend_topic: str, best_recalled: dict[str, Any] | None
) -> tuple[str, str]:
    """Generate headline/body that actually reflects the decision made,
    instead of a hash-selected line from a fixed bank."""
    if decision == "pivot_angle" and best_recalled:
        headline = f"{product}: the angle that worked for {best_recalled['campaign_name']}, adapted for {audience}"
        body = (
            f"Borrowing what worked elsewhere - \"{best_recalled['headline']}\" performed well for a similar "
            f"audience. Here's {product} through that same lens for {audience}."
        )
    elif decision == "pivot_channel":
        headline = f"{product} - same message, a different room"
        body = (
            f"{audience.title()} weren't responding on the last channel. Same core value prop for {product}, "
            f"tried somewhere new this cycle."
        )
    elif decision == "kill":
        headline = f"[Recommend stopping] {product} angle isn't converting for {audience}"
        body = (
            f"Sustained underperformance across recent cycles. Recommending we stop spending against this "
            f"direction rather than keep iterating on it."
        )
    elif decision == "tweak":
        headline = f"{product}: a sharper version of what's already working"
        body = f"Small edit, same core idea - {product} for {audience}, tightened based on the last cycle's numbers."
    else:  # keep
        if trend_topic:
            headline = f"{product} for {audience} - tied to what's trending in {trend_topic}"
        else:
            headline = f"{product}, built for how {audience} actually works"
        body = (
            f"{product} is what {audience} reach for when the old way stops working. Staying the course this "
            f"cycle - it's working."
        )
    return headline, body


def _draft_image_prompt(decision: str, product: str, audience: str, trend_topic: str) -> str:
    """Mirrors _draft_copy but for the visual direction - deterministic, but
    still responsive to the decision so mock mode's image prompt actually
    changes shape on a pivot instead of being a static placeholder."""
    if decision == "pivot_angle":
        return f"{product} shown in a completely different setting/use-case for {audience}, bold new visual angle, no text"
    if decision == "pivot_channel":
        return f"{product}, native-feeling creative styled for a different platform, candid and less polished, no text"
    if decision == "kill":
        return f"{product}, muted and understated composition, no text"
    if decision == "tweak":
        return f"{product} in use by {audience}, same visual concept as before with sharper lighting and framing, no text"
    base = f"{product} in everyday use by {audience}, clean modern product photography, no text"
    return f"{base}, subtle nod to {trend_topic}" if trend_topic else base


def _mock_strategy(context: dict[str, Any]) -> dict[str, Any]:
    product = context.get("product", "the product")
    audience = context.get("audience_segment", "the audience")
    recent: list[dict[str, Any]] = context.get("recent_cycles") or []
    recalled: list[dict[str, Any]] = context.get("recalled_memory") or []
    trend_topic = context.get("trend_topic", "")
    trend_score = float(context.get("trend_score", 0.0) or 0.0)
    evidence = float(context.get("evidence_strength", 0.2) or 0.2)
    human_feedback = context.get("human_feedback")

    # --- performance assessment: read the campaign's own recent history ---
    ctr_delta = None
    if not recent:
        perf_assessment = "No performance history yet for this campaign - this is the baseline cycle."
    elif len(recent) == 1:
        c = recent[-1]
        perf_assessment = (
            f"Only one prior cycle: {(c['ctr'] or 0):.2%} CTR, {c['conversions']} conversions - "
            f"too early to call a trend."
        )
    else:
        first_ctr = recent[0]["ctr"] or 0.0
        last_ctr = recent[-1]["ctr"] or 0.0
        ctr_delta = last_ctr - first_ctr
        direction = "up" if ctr_delta > 0.002 else "down" if ctr_delta < -0.002 else "flat"
        perf_assessment = (
            f"CTR has moved {direction} from {first_ctr:.2%} to {last_ctr:.2%} across the last "
            f"{len(recent)} cycles ({recent[-1]['conversions']} conversions on the latest run)."
        )

    # --- memory assessment: does recalled precedent actually help? ---
    current_ctr = recent[-1]["ctr"] if recent else None
    scored_recall = [r for r in recalled if r.get("outcome")]
    best_recalled = max(scored_recall, key=lambda r: r["outcome"]["ctr"]) if scored_recall else None

    if best_recalled and current_ctr and best_recalled["outcome"]["ctr"] > current_ctr * 1.3:
        memory_assessment = (
            f"\"{best_recalled['headline']}\" from {best_recalled['campaign_name']} "
            f"({best_recalled['region']}) is {best_recalled['similarity']:.0%} similar and scored "
            f"{best_recalled['outcome']['ctr']:.2%} CTR - meaningfully better than this campaign's current run."
        )
    elif best_recalled:
        memory_assessment = (
            f"Closest precedent is \"{best_recalled['headline']}\" from {best_recalled['campaign_name']} "
            f"at {best_recalled['outcome']['ctr']:.2%} CTR - in the same range as this campaign, not a "
            f"strong signal either way."
        )
    elif recalled:
        memory_assessment = "Found a similar ad in memory but no completed outcome to compare against yet."
    else:
        memory_assessment = "No precedent found in memory yet - this is effectively cold-start for this kind of campaign."

    # --- trend assessment ---
    if trend_score >= 0.6:
        trend_assessment = f"'{trend_topic}' is trending strongly (score {trend_score:.2f}) - worth leaning into."
    elif trend_score >= 0.35:
        trend_assessment = f"'{trend_topic}' has moderate signal (score {trend_score:.2f}) - a minor factor, not decisive."
    else:
        trend_assessment = f"'{trend_topic}' isn't trending meaningfully right now (score {trend_score:.2f}) - treating it as noise."

    # --- decision ---
    if not recent:
        decision = "keep"
    elif best_recalled and current_ctr and best_recalled["outcome"]["ctr"] > current_ctr * 1.3 and best_recalled["similarity"] > 0.55:
        decision = "pivot_angle"
    elif ctr_delta is not None and ctr_delta < -0.004 and len(recent) >= 3:
        decision = "pivot_channel"
    elif ctr_delta is not None and ctr_delta < -0.001:
        decision = "tweak"
    elif ctr_delta is not None and ctr_delta > 0.003:
        decision = "keep"
    else:
        decision = "tweak"

    # Chronic-failure floor is relative to this campaign's OWN first-cycle
    # CTR, not one fixed number for every vertical - a B2B agricultural
    # campaign and a consumer retail campaign have no business being judged
    # against the same absolute benchmark. Falls back to a conservative
    # absolute floor only in the (rare) case no baseline is available yet.
    baseline_ctr = context.get("baseline_ctr")
    failure_threshold = (baseline_ctr * 0.5) if baseline_ctr else 0.012
    if len(recent) >= 3 and all((c["ctr"] or 0) < failure_threshold for c in recent[-3:]):
        decision = "kill"

    rationale = (
        f"{decision.replace('_', ' ').title()} call based on the campaign's own performance trend, "
        f"what similar ads have actually done elsewhere, and whether the live trend is relevant."
    )
    if human_feedback:
        rationale += f' Redrafted per reviewer feedback: "{human_feedback}".'

    headline, body = _draft_copy(decision, product, audience, trend_topic, best_recalled)
    headline, body = _apply_feedback(headline, body, human_feedback)
    image_prompt = _draft_image_prompt(decision, product, audience, trend_topic)

    return {
        "decision": decision,
        "performance_assessment": perf_assessment,
        "memory_assessment": memory_assessment,
        "trend_assessment": trend_assessment,
        "rationale": rationale,
        "headline": headline,
        "body": body,
        "image_prompt": image_prompt,
        "confidence": round(min(0.9, 0.35 + evidence), 2),
    }


def _parse_data_url(data_url: str) -> tuple[str, str] | None:
    """'data:image/png;base64,AAAA...' -> ('image/png', 'AAAA...'). Returns
    None for anything that isn't a base64 data: URL (defensive - a prior
    image should always be one, since that's the only shape we ever write,
    but a malformed/foreign value shouldn't crash a whole reasoning cycle)."""
    match = re.match(r"^data:([\w/.+-]+);base64,(.+)$", data_url, re.DOTALL)
    if not match:
        return None
    return match.group(1), match.group(2)


def embed_text(text: str) -> list[float]:
    settings = get_settings()
    if settings.use_mock_llm:
        return _mock_embedding(text, settings.embedding_dimensions)

    import boto3

    client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
    resp = client.invoke_model(
        modelId=settings.bedrock_embedding_model_id,
        body=json.dumps({"inputText": text}),
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(resp["body"].read())
    return payload["embedding"]


def generate_strategy(context: dict[str, Any]) -> dict[str, Any]:
    """context keys: product, audience_segment, goal, tone, recent_cycles
    (list), recalled_memory (list, each with an 'outcome' sub-dict or None),
    trend_topic, trend_score, evidence_strength, budget_usd, baseline_ctr,
    human_feedback (optional str, set when regenerating a rejected draft),
    prior_image_data_url (optional str, the most recent published cycle's
    creative - sent to Claude as an actual vision input, not JSON text; see
    prior_ad_image in _STRATEGY_SYSTEM_PROMPT)."""
    settings = get_settings()
    if settings.use_mock_llm:
        return _mock_strategy(context)

    import boto3

    client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
    prior_image_data_url = context.get("prior_image_data_url")
    # Excluded from the JSON text dump below - it's sent as a real image
    # content block instead (see content_blocks), not duplicated as base64
    # text in the prompt. Built from a shallow copy so the caller's dict
    # (which may get logged elsewhere) is never mutated by this call.
    text_context = {k: v for k, v in context.items() if k != "prior_image_data_url"}
    user_prompt = (
        "CAMPAIGN CONTEXT:\n"
        f"{json.dumps(text_context, indent=2, default=str)}\n\n"
        "Decide and draft the ad now."
    )
    content_blocks: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    parsed_image = _parse_data_url(prior_image_data_url) if prior_image_data_url else None
    if parsed_image:
        media_type, b64_data = parsed_image
        content_blocks.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64_data},
            }
        )
        content_blocks.append(
            {"type": "text", "text": "^ this is prior_ad_image - the creative from this campaign's most recent published cycle."}
        )
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 800,
            "system": _STRATEGY_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": content_blocks}],
        }
    )
    resp = client.invoke_model(
        modelId=settings.bedrock_text_model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(resp["body"].read())
    raw_text = payload["content"][0]["text"]
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        logger.warning("Bedrock response had no JSON block, falling back to mock strategy")
        return _mock_strategy(context)
    parsed = json.loads(match.group(0))
    if parsed.get("decision") not in DECISIONS:
        logger.warning("Bedrock returned an unrecognized decision %r, falling back to mock strategy", parsed.get("decision"))
        return _mock_strategy(context)
    return parsed


def _hash_float(seed: str) -> float:
    """Deterministic pseudo-random value in [0, 1) from a string seed."""
    return (int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % 10_000) / 10_000


def _mock_image(prompt: str) -> str:
    """Dependency-free deterministic placeholder: an inline SVG (no PIL/
    Pillow needed). Deliberately does NOT try to look like a real photo -
    it's a soft blurred-gradient-blob composition (the same visual language
    real placeholder/loading-state generators use) plus a short, truncated
    caption in a proper text block, not the full prompt dumped edge-to-edge.
    Different prompts still visibly render differently (hue + blob layout
    both derive from the prompt's hash) without pretending to be a finished
    ad. See generate_image()'s docstring for why this exists at all."""
    import base64

    hue = int(_hash_float(prompt) * 360)
    hue2 = (hue + 130) % 360
    hue3 = (hue + 260) % 360

    blobs = ""
    for i, bhue in enumerate((hue, hue2, hue3)):
        bx = 60 + _hash_float(f"{prompt}:x{i}") * 392
        by = 60 + _hash_float(f"{prompt}:y{i}") * 330
        br = 95 + _hash_float(f"{prompt}:r{i}") * 75
        opacity = 0.4 + _hash_float(f"{prompt}:o{i}") * 0.25
        blobs += f'<circle cx="{bx:.0f}" cy="{by:.0f}" r="{br:.0f}" fill="hsl({bhue},55%,65%)" opacity="{opacity:.2f}"/>'

    caption = prompt.strip().split("no text")[0].strip(" ,.-") or prompt.strip()
    if len(caption) > 56:
        caption = caption[:54].rsplit(" ", 1)[0] + "…"
    caption = caption.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="hsl({hue},32%,22%)"/>
      <stop offset="100%" stop-color="hsl({hue2},32%,14%)"/>
    </linearGradient>
    <filter id="soften" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="46"/>
    </filter>
  </defs>
  <rect width="512" height="512" fill="url(#bg)"/>
  <g filter="url(#soften)">{blobs}</g>
  <rect x="24" y="408" width="464" height="80" rx="14" fill="black" opacity="0.32"/>
  <text x="44" y="436" font-family="sans-serif" font-size="11" letter-spacing="2" fill="white" opacity="0.6">AI CONCEPT · PLACEHOLDER</text>
  <text x="44" y="464" font-family="sans-serif" font-size="17" fill="white">{caption}</text>
</svg>"""
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def generate_image(prompt: str) -> str | None:
    """Returns a data: URL (image/png live, image/svg+xml mock) or None if
    generation fails/isn't available - the image is additive, never load-
    bearing, so a Bedrock image-model access issue (e.g. not yet granted in
    this account/region, same story as text-model access) degrades to 'no
    image this cycle' rather than failing the whole cycle."""
    settings = get_settings()
    if settings.use_mock_llm:
        return _mock_image(prompt)

    import boto3

    try:
        client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
        body = json.dumps(
            {
                "taskType": "TEXT_IMAGE",
                "textToImageParams": {"text": prompt[:512]},
                "imageGenerationConfig": {"numberOfImages": 1, "height": 512, "width": 512, "cfgScale": 8.0},
            }
        )
        resp = client.invoke_model(
            modelId=settings.bedrock_image_model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        payload = json.loads(resp["body"].read())
        images = payload.get("images") or []
        if not images:
            logger.warning("Bedrock image model returned no images (prompt may have been filtered)")
            return None
        return f"data:image/png;base64,{images[0]}"
    except Exception:
        logger.exception("generate_image failed - continuing cycle without a creative image")
        return None
