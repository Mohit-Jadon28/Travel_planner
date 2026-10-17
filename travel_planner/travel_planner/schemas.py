
from __future__ import annotations

import operator
from typing import Annotated, Any, List, Optional, TypedDict

from pydantic import BaseModel, Field

from .guardrails import sanitize_free_text
from .config import GUARDRAILS


class TravelRequest(BaseModel):
    origin: str
    destination: str

    total_budget: float
    currency: str = "INR"
    display_currency: Optional[str] = None

    travelers: int = 1
    days: int = 3

    travel_style: str = "balanced"
    hotel_preference: str = "comfortable"
    food_preference: str = "local"

    interests: List[str] = Field(default_factory=lambda: ["tourist attractions"])
    notes: Optional[str] = None

    reference_files: List[str] = Field(default_factory=list)

    def model_post_init(self, __context) -> None:
        object.__setattr__(self, "notes", sanitize_free_text(self.notes or "", GUARDRAILS["max_notes_chars"]))


class FlightResult(BaseModel):
    options: List[str] = Field(default_factory=list)
    recommended_option: str = ""
    estimated_cost: float = 0
    reason: str = ""


class HotelResult(BaseModel):
    area_recommendation: str = ""
    hotel_options: List[str] = Field(default_factory=list)
    recommended_hotel: str = ""
    estimated_total_cost: float = 0
    reason: str = ""


class FoodResult(BaseModel):
    daily_food_budget: float = 0
    restaurants: List[str] = Field(default_factory=list)
    recommended_food_plan: str = ""


class AttractionResult(BaseModel):
    day_1: List[str] = Field(default_factory=list)
    day_2: List[str] = Field(default_factory=list)
    day_3: List[str] = Field(default_factory=list)
    estimated_activity_cost: float = 0


class TransportResult(BaseModel):
    recommended_transport: str = ""
    daily_strategy: str = ""
    estimated_transport_cost: float = 0


class BudgetResult(BaseModel):
    flight: float = 0
    hotel: float = 0
    food: float = 0
    transport: float = 0
    activities: float = 0
    buffer: float = 0
    total: float = 0
    budget: float = 0
    remaining: float = 0
    within_budget: bool = True
    optimization_needed: bool = False
    recommendations: List[str] = Field(default_factory=list)
    display_currency: Optional[str] = None
    total_in_display_currency: Optional[float] = None


class OptimizerResult(BaseModel):
    optimized_strategy: str = ""
    cost_reduction_actions: List[str] = Field(default_factory=list)
    estimated_savings: float = 0


class OrchestratorPlan(BaseModel):
    strategy: str = "balanced"
    agents: List[str] = Field(default_factory=lambda: ["flight", "hotel", "food", "attraction", "transport"])
    critical_constraints: List[str] = Field(default_factory=list)
    budget_allocation_notes: str = ""


class CriticResult(BaseModel):
    quality_score: int = 0
    issues: List[str] = Field(default_factory=list)
    approved: bool = True


class TravelState(TypedDict):
    user_id: str
    request: dict[str, Any]
    plan: dict[str, Any]
    skill_context: str
    force_refresh: bool

    flight_results: dict[str, Any]
    hotel_results: dict[str, Any]
    food_results: dict[str, Any]
    attraction_results: dict[str, Any]
    transport_results: dict[str, Any]

    budget_result: dict[str, Any]
    optimization_rounds: int

    critique_result: dict[str, Any]
    critique_rounds: int

    final_plan: dict[str, Any]

    errors: Annotated[List[str], operator.add]
    execution_log: Annotated[List[str], operator.add]
    resource_usage: Annotated[List[dict[str, Any]], operator.add]
    loop_trace: Annotated[List[str], operator.add]
