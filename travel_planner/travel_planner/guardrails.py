
from __future__ import annotations

import re
from typing import Any

from .config import GUARDRAILS


class GuardrailReport(list):
    """A list of human-readable warning strings. Truthy if non-empty."""


def _find_banned(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [kw for kw in GUARDRAILS["banned_keywords"] if kw in lowered]


def sanitize_free_text(text: str, max_chars: int) -> str:
    """Strip likely prompt-injection phrases and cap length before anything
    user-supplied (notes, uploaded documents) reaches an LLM prompt."""
    if not text:
        return ""
    text = text[:max_chars]
    for pat in GUARDRAILS["injection_patterns"]:
        text = re.sub(pat, "[filtered]", text, flags=re.IGNORECASE)
    return text


def input_guardrail(request) -> GuardrailReport:
    """Validate a TravelRequest before any LLM call is made. Cheap, and
    catches most bad requests before they cost a single token."""
    report = GuardrailReport()
    days = max(1, request.days)
    travelers = max(1, request.travelers)
    per_person_per_day = request.total_budget / (days * travelers)

    if per_person_per_day < GUARDRAILS["min_budget_per_day_per_person"]:
        report.append(
            f"Budget looks very tight: ~{per_person_per_day:,.0f} {request.currency}/person/day. "
            "The plan may need to cut corners aggressively."
        )
    if per_person_per_day > GUARDRAILS["max_budget_per_day_per_person"]:
        report.append(
            f"Budget looks unusually high (~{per_person_per_day:,.0f} {request.currency}/person/day) "
            "— double-check it."
        )
    if request.days > GUARDRAILS["max_days"]:
        report.append(f"Trip length capped at {GUARDRAILS['max_days']} days for this system.")
    if request.travelers > GUARDRAILS["max_travelers"]:
        report.append(f"Traveler count capped at {GUARDRAILS['max_travelers']} for this system.")

    combined = " ".join([request.notes or "", " ".join(request.interests), request.destination, request.origin])
    hits = _find_banned(combined)
    if hits:
        report.append(f"Request references disallowed activity keywords: {hits}. These will be ignored.")

    return report


def output_guardrail(plan_text: str, budget_result: dict[str, Any],
                      request: dict[str, Any]) -> tuple[GuardrailReport, str]:
    """Validate the final generated itinerary. Returns (warnings, possibly-trimmed text)."""
    report = GuardrailReport()
    plan_text = plan_text or ""

    if len(plan_text) < 200:
        report.append("Final plan looks unusually short — it may be incomplete.")

    max_chars = GUARDRAILS["max_output_chars"]
    if len(plan_text) > max_chars:
        plan_text = plan_text[:max_chars] + "\n\n*(truncated to keep the document a reasonable size)*"
        report.append(f"Output trimmed to {max_chars} characters.")

    hits = _find_banned(plan_text)
    if hits:
        report.append(f"Output referenced disallowed keywords {hits} — please review before sharing.")

    total = (budget_result or {}).get("total", 0) or 0
    budget = (request or {}).get("total_budget", 0) or 0
    if budget and total > budget * 1.15:
        report.append(f"Estimated total ({total:,.0f}) exceeds the requested budget ({budget:,.0f}) by more than 15%.")

    return report, plan_text
