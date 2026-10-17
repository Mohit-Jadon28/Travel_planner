
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSkill:
    name: str
    objective: str
    evidence_rule: str
    required_fields: tuple[str, ...]
    allowed_tools: tuple[str, ...]

    def prompt_block(self) -> str:
        fields = ", ".join(self.required_fields)
        tools = ", ".join(self.allowed_tools) or "none"
        return (
            f"SKILL: {self.name}\n"
            f"Objective: {self.objective}\n"
            f"Evidence rule: {self.evidence_rule}\n"
            f"Required fields: {fields}\n"
            f"Allowed tools: {tools}"
        )


AGENT_SKILLS: dict[str, AgentSkill] = {
    "flight": AgentSkill(
        name="Flight research",
        objective="Compare practical route options, cost, duration, and stops.",
        evidence_rule="Use search findings for prices and schedules; label uncertain details as estimates.",
        required_fields=("options", "recommended_option", "estimated_cost", "reason"),
        allowed_tools=("tavily_search",),
    ),
    "hotel": AgentSkill(
        name="Hotel research",
        objective="Find comfortable, budget-compatible stays near the requested area.",
        evidence_rule="Prefer properties supported by findings and explain location, price, and tradeoffs.",
        required_fields=("area_recommendation", "hotel_options", "recommended_hotel", "estimated_total_cost", "reason"),
        allowed_tools=("tavily_search",),
    ),
    "food": AgentSkill(
        name="Food planning",
        objective="Build a realistic food plan matching dietary preferences and daily budget.",
        evidence_rule="Give specific restaurants or local dishes from findings and preserve dietary constraints.",
        required_fields=("daily_food_budget", "restaurants", "recommended_food_plan"),
        allowed_tools=("tavily_search",),
    ),
    "attraction": AgentSkill(
        name="Attraction planning",
        objective="Create a day-by-day attraction plan aligned with interests and trip length.",
        evidence_rule="Cover the requested interests, include timing-friendly activities, and use weather when available.",
        required_fields=("day_1", "day_2", "day_3", "estimated_activity_cost"),
        allowed_tools=("tavily_search", "weather_api"),
    ),
    "transport": AgentSkill(
        name="Local transport planning",
        objective="Choose practical intercity and local transport within the budget.",
        evidence_rule="State the mode, daily usage pattern, and estimated cost; avoid unsupported precision.",
        required_fields=("recommended_transport", "daily_strategy", "estimated_transport_cost"),
        allowed_tools=("tavily_search",),
    ),
}


def get_skill(agent_name: str) -> AgentSkill:
    try:
        return AGENT_SKILLS[agent_name]
    except KeyError as exc:
        raise ValueError(f"Unknown research skill: {agent_name}") from exc
