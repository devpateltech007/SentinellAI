"""AI-assisted evaluation suggestions for controls with no matching rules."""

import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

SUGGESTION_PROMPT = """You are a compliance evaluation advisor. A compliance control could not be
automatically evaluated because no automated rule exists for it.

Control: {control_id_code} — {title}
Description: {description}

Available Evidence Summary:
{evidence_summary}

Based on the control description and available evidence, provide:
1. What specific fields or patterns in the evidence should be checked
2. What would constitute a PASS vs FAIL for this control
3. What additional evidence sources might be needed

Keep your response under 200 words. Be specific and actionable."""


async def suggest_evaluation_approach(
    control_id_code: str,
    title: str,
    description: str,
    evidence_items: list[dict],
) -> str:
    """Generate AI-powered evaluation guidance for unmatched controls."""
    if not settings.GEMINI_API_KEY:
        return (
            "No automated evaluation rule exists for this control. "
            "Manual review required by compliance manager."
        )

    # Summarize evidence for the prompt (avoid sending full content)
    evidence_lines = []
    for i, ev in enumerate(evidence_items[:5]):  # limit to 5 items
        src = ev.get("source_type", "unknown")
        ref = ev.get("source_ref", "unknown")[:100]
        keys = list(ev.get("content_json", {}).keys())[:10]
        evidence_lines.append(f"  {i+1}. [{src}] {ref} — keys: {keys}")

    evidence_summary = "\n".join(evidence_lines) if evidence_lines else "  No evidence available."

    try:
        client = AsyncOpenAI(
            api_key=settings.GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        resp = await client.chat.completions.create(
            model="gemini-1.5-flash",
            messages=[{
                "role": "user",
                "content": SUGGESTION_PROMPT.format(
                    control_id_code=control_id_code,
                    title=title,
                    description=description,
                    evidence_summary=evidence_summary,
                ),
            }],
            temperature=0.3,
            max_tokens=300,
        )
        content = resp.choices[0].message.content
        if not content:
            raise ValueError("OpenAI returned empty content")
        suggestion = content.strip()
        return f"AI Evaluation Guidance: {suggestion}"
    except Exception:
        logger.exception("AI rule suggestion failed for %s", control_id_code)
        return (
            "No automated evaluation rule exists for this control. "
            "AI suggestion unavailable. Manual review required."
        )
