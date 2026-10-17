
from __future__ import annotations

import functools
from datetime import datetime
from typing import Any, Callable, Optional

from .config import RESOURCE_CONFIG, MAX_OPTIMIZATION_ROUNDS, MAX_CRITIQUE_ROUNDS, COMPRESSION
from .guardrails import output_guardrail
from .memory_store import MEMORY
from .resource_manager import ResourceManager
from .schemas import (
    TravelState, FlightResult, HotelResult, FoodResult, AttractionResult,
    TransportResult, BudgetResult, OptimizerResult, OrchestratorPlan, CriticResult,
)
from .tools import structured_llm, perform_research, get_destination_weather, convert_currency, llm
from .document_skill import document_skill
from .utils import call_with_retry, truncate_json, log_event
from .skills import get_skill

SUBAGENT_SPAWN_LOG: list[dict[str, Any]] = []
_spawn_counter = {"n": 0}
RESEARCH_AGENTS = ("flight", "hotel", "food", "attraction", "transport")


def safe_node(name: str):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(state):
            try:
                return fn(state)
            except Exception as e:  # noqa: BLE001
                err = f"[{name}] failed: {e}"
                print("[ERROR]", err)
                return {"errors": [err], "execution_log": [f"{name.upper()}: ERROR - {e}"]}
        return wrapper
    return decorator


def create_context_packet(state: TravelState, agent_name: str) -> dict[str, Any]:
    r = state["request"]
    return {
        "agent": agent_name,
        "origin": r.get("origin"),
        "destination": r.get("destination"),
        "days": r.get("days"),
        "travelers": r.get("travelers"),
        "total_budget": r.get("total_budget"),
        "currency": r.get("currency"),
        "preferences": {
            "travel_style": r.get("travel_style"),
            "hotel": r.get("hotel_preference"),
            "food": r.get("food_preference"),
            "interests": r.get("interests"),
        },
    }


def robust_structured_call(resource: ResourceManager, build_prompt: Callable[[Optional[str]], str],
                            schema: type) -> dict[str, Any]:
    last_error = None
    for _ in range(resource.max_llm_retries + 1):
        prompt = resource.enforce_input_budget(build_prompt(last_error))
        try:
            if not resource.reserve_llm_call():
                last_error = resource.last_error
                break
            sllm = structured_llm(schema)
            response = call_with_retry(sllm.invoke, prompt, max_attempts=1)
            parsed = response.get("parsed") if isinstance(response, dict) else None
            raw = response.get("raw") if isinstance(response, dict) else None
            raw_text = getattr(raw, "content", "") if raw is not None else ""
            if parsed is not None:
                resource.record_llm_call(prompt, raw_text or __import__("json").dumps(parsed.model_dump(), default=str))
                out = parsed.model_dump()
                out["_valid"] = True
                return out
            last_error = str(response.get("parsing_error")) if isinstance(response, dict) else "no parsed output"
            resource.record_llm_call(prompt, raw_text)
        except Exception as e:  # noqa: BLE001
            last_error = str(e)
            resource.record_llm_failure(prompt, last_error)
        resource.retries_used += 1
    out = schema().model_dump()
    out["_valid"] = False
    return out


# ---------------------------------------------------------------- orchestrator

@safe_node("orchestrator")
def orchestrator_node(state: TravelState):
    request = state["request"]
    resource = ResourceManager("orchestrator", **RESOURCE_CONFIG["orchestrator"])

    skill_context = document_skill.read_all(request.get("reference_files", []))

    def build_prompt(last_error):
        feedback = f"\nPrevious attempt error: {last_error}. Fix it and answer again." if last_error else ""
        extra = f"\n\nReference material (already sanitized/compressed):\n{skill_context}" if skill_context else ""
        return (
            "ROLE: You are the Orchestrator of a multi-agent travel-planning system.\n"
            "TASK: Decide the overall strategy (cheap / balanced / premium), which "
            "research subagents to run, the hard constraints they must respect, and "
            "any budget-allocation guidance.\n"
            "OUTPUT: Fill the provided schema only — no prose outside it.\n\n"
            f"Request: {truncate_json(request, 500)}{extra}{feedback}"
        )

    result = robust_structured_call(resource, build_prompt, schema=OrchestratorPlan)
    plan = {k: v for k, v in result.items() if not k.startswith("_")}
    if not result.get("_valid", False):
        plan = OrchestratorPlan().model_dump()
    plan["agents"] = list(RESEARCH_AGENTS)

    log_event("ORCHESTRATOR OUTPUT", plan)
    print(f"   \U0001F4CB Orchestrator dispatching subagents: {plan.get('agents', [])}")

    return {
        "plan": plan,
        "skill_context": skill_context,
        "resource_usage": [resource.summary()],
        "execution_log": [
            f"ORCHESTRATOR: strategy set ({resource.llm_calls_used} LLM call(s), "
            f"{resource.input_tokens + resource.output_tokens} tokens)"
        ],
    }


# ---------------------------------------------------------------- research subagents

def run_research_subagent(
    agent_name: str,
    state: TravelState,
    schema: type,
    query_builder: Callable[[dict[str, Any]], str],
    role_description: str,
    extra_context_builder: Optional[Callable[[dict[str, Any]], str]] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    context = create_context_packet(state, agent_name)
    skill = get_skill(agent_name)

    reference_context = state.get("skill_context", "")
    cache_context = {"request": context, "reference": reference_context}
    mem_key = f"subagent::{agent_name}::{MEMORY.fingerprint(cache_context)}"
    cached_result = None
    if not state.get("force_refresh", False):
        cached_result = MEMORY.get(mem_key)
    if cached_result is not None:
        print(f"   \u267B\uFE0F  [{agent_name}] fully served from memory \u2014 no subagent spawned, 0 tokens.")
        empty_usage = {"agent": agent_name, "tool_calls_used": 0, "llm_calls_used": 0,
                        "retries_used": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        return cached_result, empty_usage

    _spawn_counter["n"] += 1
    spawn_id = f"{agent_name}-{_spawn_counter['n']:02d}"
    SUBAGENT_SPAWN_LOG.append({"id": spawn_id, "agent": agent_name, "ts": datetime.now().isoformat(timespec="seconds")})
    print(f"   \U0001F9F5 Spawning subagent [{spawn_id}] ({role_description})...")

    resource = ResourceManager(agent_name, **RESOURCE_CONFIG[agent_name])

    search_data: list[dict[str, str]] = []
    if resource.can_use_tool():
        search_data = perform_research(
            query_builder(context), force_refresh=state.get("force_refresh", False)
        )
        resource.use_tool()

    extra_note = ""
    if extra_context_builder and resource.can_use_tool():
        extra_note = extra_context_builder(context) or ""
        resource.use_tool()

    def build_prompt(last_error):
        feedback = f"\nPrevious attempt error: {last_error}. Fix it and answer again." if last_error else ""
        extra = f"\nAdditional context: {extra_note}" if extra_note else ""
        return (
            f"ROLE: You are the {role_description} in a multi-agent travel planner.\n"
            f"{skill.prompt_block()}\n"
            "TASK: Use the constraints and findings below to fill the schema with "
            "concrete, realistic recommendations. Do not invent data the findings don't support.\n"
            "OUTPUT: Schema fields only.\n\n"
            f"Constraints: {truncate_json(context, 450)}\n"
            f"Findings: {truncate_json(search_data, 500)}\n"
            f"Reference notes: {truncate_json(reference_context, 700)}{extra}{feedback}"
        )

    result = robust_structured_call(resource, build_prompt, schema=schema)
    log_event(f"{agent_name.upper()} AGENT OUTPUT [{spawn_id}]", {k: v for k, v in result.items() if not k.startswith("_")})

    if result.get("_valid", False):
        MEMORY.set(mem_key, result)

    return result, resource.summary()


@safe_node("flight")
def flight_agent(state):
    result, usage = run_research_subagent(
        "flight", state, FlightResult,
        query_builder=lambda c: f"Best flight options {c['origin']} to {c['destination']}: cost, duration, stops",
        role_description="Flight Research Agent",
    )
    return {"flight_results": result, "resource_usage": [usage],
            "execution_log": [f"FLIGHT AGENT: done ({usage['total_tokens']} tokens)"]}


@safe_node("hotel")
def hotel_agent(state):
    result, usage = run_research_subagent(
        "hotel", state, HotelResult,
        query_builder=lambda c: f"Best hotels in {c['destination']} for {c['travelers']} travelers, {c['preferences']['hotel']} preference",
        role_description="Hotel Research Agent",
    )
    return {"hotel_results": result, "resource_usage": [usage],
            "execution_log": [f"HOTEL AGENT: done ({usage['total_tokens']} tokens)"]}


@safe_node("food")
def food_agent(state):
    result, usage = run_research_subagent(
        "food", state, FoodResult,
        query_builder=lambda c: f"Best restaurants and affordable local food in {c['destination']}, {c['preferences']['food']} preference",
        role_description="Food Planning Agent",
    )
    return {"food_results": result, "resource_usage": [usage],
            "execution_log": [f"FOOD AGENT: done ({usage['total_tokens']} tokens)"]}


@safe_node("attraction")
def attraction_agent(state):
    result, usage = run_research_subagent(
        "attraction", state, AttractionResult,
        query_builder=lambda c: f"Best attractions in {c['destination']} for {c['days']} days, interests: {c['preferences']['interests']}",
        role_description="Attraction Planning Agent",
        extra_context_builder=lambda c: f"Weather outlook: {get_destination_weather(c['destination'], days=min(c['days'], 5))}",
    )
    return {"attraction_results": result, "resource_usage": [usage],
            "execution_log": [f"ATTRACTION AGENT: done ({usage['total_tokens']} tokens)"]}


@safe_node("transport")
def transport_agent(state):
    result, usage = run_research_subagent(
        "transport", state, TransportResult,
        query_builder=lambda c: f"Best local transport options within {c['destination']} for tourists",
        role_description="Local Transport Agent",
    )
    return {"transport_results": result, "resource_usage": [usage],
            "execution_log": [f"TRANSPORT AGENT: done ({usage['total_tokens']} tokens)"]}


# ---------------------------------------------------------------- aggregation

@safe_node("aggregate")
def aggregation_node(state: TravelState):
    aggregated = {
        "request": state["request"],
        "flights": state.get("flight_results"),
        "hotels": state.get("hotel_results"),
        "food": state.get("food_results"),
        "attractions": state.get("attraction_results"),
        "transport": state.get("transport_results"),
    }
    log_event("AGGREGATOR OUTPUT (combined subagent results)")
    return {
        "final_plan": aggregated,
        "execution_log": ["AGGREGATOR: combined all subagent results"],
    }


# ---------------------------------------------------------------- budget + optimizer

@safe_node("budget")
def budget_agent(state):
    request = state["request"]
    total_budget = request["total_budget"]
    data = state["final_plan"]
    resource = ResourceManager("budget", **RESOURCE_CONFIG["budget"])

    def build_prompt(last_error):
        feedback = f"\nPrevious attempt error: {last_error}. Fix it and answer again." if last_error else ""
        return (
            "ROLE: You are a strict Travel Budget Optimization Agent.\n"
            f"Total available budget: {total_budget} {request['currency']}\n\n"
            f"Travel data: {truncate_json(data, COMPRESSION['prior_state_chars'])}\n\n"
            "TASK: Estimate cost for flight, hotel, food, transport, activities, and a "
            "small buffer. Set optimization_needed=true if the total exceeds the budget.\n"
            f"OUTPUT: Schema fields only.{feedback}"
        )

    result = robust_structured_call(resource, build_prompt, schema=BudgetResult)
    budget_result = {k: v for k, v in result.items() if not k.startswith("_")}
    if not result.get("_valid", False):
        budget_result = BudgetResult(budget=total_budget).model_dump()

    display_ccy = request.get("display_currency")
    if display_ccy and display_ccy != request["currency"]:
        converted = convert_currency(budget_result.get("total", 0), request["currency"], display_ccy)
        if converted is not None:
            budget_result["display_currency"] = display_ccy
            budget_result["total_in_display_currency"] = converted

    log_event("BUDGET AGENT OUTPUT", budget_result)
    needs_optimization = bool(
        budget_result.get("optimization_needed")
        and state.get("optimization_rounds", 0) < MAX_OPTIMIZATION_ROUNDS
    )

    return {
        "budget_result": budget_result,
        "resource_usage": [resource.summary()],
        "execution_log": [
            f"BUDGET AGENT: analysis done (round {state.get('optimization_rounds', 0)}, "
            f"{resource.input_tokens + resource.output_tokens} tokens)"
        ],
        "loop_trace": [
            f"budget_loop: {'continue to optimizer' if needs_optimization else 'finalize'} "
            f"(round={state.get('optimization_rounds', 0)}, max={MAX_OPTIMIZATION_ROUNDS})"
        ],
    }


def budget_router(state):
    try:
        budget = state.get("budget_result", {})
        rounds = state.get("optimization_rounds", 0)
        if budget.get("optimization_needed") and rounds < MAX_OPTIMIZATION_ROUNDS:
            return "optimize"
        return "finalize"
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] budget_router failed ({e}); defaulting to finalize")
        return "finalize"


@safe_node("optimizer")
def optimization_agent(state):
    budget = state["budget_result"]
    resource = ResourceManager("optimizer", **RESOURCE_CONFIG["optimizer"])

    def build_prompt(last_error):
        feedback = f"\nPrevious attempt error: {last_error}. Fix it and answer again." if last_error else ""
        return (
            "ROLE: You are a Travel Cost Optimization Agent.\n"
            f"Current budget breakdown: {truncate_json(budget, 700)}\n\n"
            "TASK: Propose concrete cost-reduction actions (cheaper hotel tier, off-peak "
            "flight, fewer paid activities, etc.) and estimate total savings.\n"
            f"OUTPUT: Schema fields only.{feedback}"
        )

    result = robust_structured_call(resource, build_prompt, schema=OptimizerResult)
    optimized = {k: v for k, v in result.items() if not k.startswith("_")}

    log_event("OPTIMIZER OUTPUT", optimized)

    return {
        "optimization_rounds": state.get("optimization_rounds", 0) + 1,
        "resource_usage": [resource.summary()],
        "execution_log": [
            f"OPTIMIZER: round {state.get('optimization_rounds', 0) + 1} "
            f"({resource.input_tokens + resource.output_tokens} tokens)"
        ],
    }


# ---------------------------------------------------------------- final planner + critic

@safe_node("final")
def final_planner(state):
    resource = ResourceManager("final", **RESOURCE_CONFIG["final"])
    compact_context = {
        "request": state["request"],
        "flight": state.get("flight_results"),
        "hotel": state.get("hotel_results"),
        "food": state.get("food_results"),
        "attractions": state.get("attraction_results"),
        "transport": state.get("transport_results"),
        "budget": state.get("budget_result"),
    }

    critique = state.get("critique_result", {})
    revision_note = ""
    if critique.get("issues"):
        revision_note = "\nFix these issues from the previous draft:\n" + "\n".join(f"- {i}" for i in critique["issues"])

    prompt = (
        "ROLE: You are the Final Travel Planner, writing for the traveler directly.\n"
        "TASK: Using ONLY the data below, write a practical, well-structured itinerary. "
        "Do not invent options the data doesn't support. Provide thorough and descriptive details for each section.\n\n"
        f"Data: {truncate_json(compact_context, 1400)}{revision_note}\n\n"
        "FORMAT: Markdown, exactly these sections in this order:\n"
        "# TRIP OVERVIEW\n# RECOMMENDED FLIGHT\n# WHERE TO STAY\n"
        "# DAY BY DAY ITINERARY (For each day, provide exhaustive details for Morning, Afternoon, Evening, Dinner, and Transportation per day)\n"
        "# FOOD PLAN\n# LOCAL TRANSPORT PLAN\n# TOTAL BUDGET (markdown cost table)\n"
        "# SAVINGS\n# IMPORTANT TIPS\n\nKeep it practical, concrete, and descriptive."
    )

    prompt = resource.enforce_input_budget(prompt)
    if not resource.reserve_llm_call():
        return {
            "final_plan": {
                "travel_plan": "LLM call limit reached before the final itinerary could be generated.",
                "resource_usage_summary": state.get("resource_usage", []),
            },
            "resource_usage": [resource.summary()],
            "errors": [resource.last_error],
            "execution_log": [f"FINAL PLANNER: skipped ({resource.last_error})"],
        }
    response = call_with_retry(llm.invoke, prompt)
    plan_text = response.content
    resource.record_llm_call(prompt, plan_text)

    log_event("FINAL PLANNER OUTPUT (preview)", None)
    print(plan_text[:600])

    return {
        "final_plan": {"travel_plan": plan_text, "resource_usage_summary": state.get("resource_usage", [])},
        "resource_usage": [resource.summary()],
        "execution_log": [
            f"FINAL PLANNER: generated itinerary draft ({resource.llm_calls_used} LLM call(s), "
            f"{resource.input_tokens + resource.output_tokens} tokens)"
        ],
    }


@safe_node("critic")
def critic_agent(state):
    plan_text = state["final_plan"].get("travel_plan", "")
    plan_excerpt = plan_text[: COMPRESSION["prior_state_chars"]]
    request = state["request"]
    resource = ResourceManager("critic", **RESOURCE_CONFIG["critic"])
    rounds = state.get("critique_rounds", 0) + 1

    def build_prompt(last_error):
        feedback = f"\nPrevious attempt error: {last_error}. Fix it and answer again." if last_error else ""
        return (
            "ROLE: You are a meticulous Travel Plan Critic.\n"
            f"Original request: {truncate_json(request, 400)}\n\n"
            f"Draft plan:\n{plan_excerpt}\n\n"
            "TASK: Score quality 0-100, list concrete issues (missing sections, unrealistic "
            "costs, budget overrun, vague recommendations), and set approved=true only if the "
            "plan is complete, realistic, and within budget.\n"
            f"OUTPUT: Schema fields only.{feedback}"
        )

    result = robust_structured_call(resource, build_prompt, schema=CriticResult)
    critique = {k: v for k, v in result.items() if not k.startswith("_")}
    loop_decision = "finish" if critique.get("approved") else "revise"
    if rounds >= MAX_CRITIQUE_ROUNDS and not critique.get("approved"):
        critique["max_rounds_reached"] = True
        loop_decision = "finish_with_unresolved_issues"

    log_event("CRITIC OUTPUT", critique)

    return {
        "critique_result": critique,
        "critique_rounds": rounds,
        "resource_usage": [resource.summary()],
        "execution_log": [
            f"CRITIC: round {rounds} — approved={critique.get('approved')} "
            f"({resource.input_tokens + resource.output_tokens} tokens)"
        ],
        "loop_trace": [
            f"critic_loop: {loop_decision} (round={rounds}, max={MAX_CRITIQUE_ROUNDS}, "
            f"quality={critique.get('quality_score', 0)})"
        ],
    }


def critic_router(state):
    critique = state.get("critique_result", {})
    if critique.get("approved"):
        return "done"
    if state.get("critique_rounds", 0) >= MAX_CRITIQUE_ROUNDS:
        return "done"
    return "revise"


# ---------------------------------------------------------------- output guardrail

@safe_node("guardrail")
def guardrail_node(state):
    plan_text = state["final_plan"].get("travel_plan", "")
    warnings, plan_text = output_guardrail(plan_text, state.get("budget_result", {}), state["request"])

    final_plan = dict(state["final_plan"])
    final_plan["travel_plan"] = plan_text
    final_plan["guardrail_warnings"] = list(warnings)
    critique = state.get("critique_result", {})
    if critique.get("max_rounds_reached") and not critique.get("approved"):
        warnings.append("Critic loop reached its maximum rounds with unresolved quality issues.")
        final_plan["guardrail_warnings"] = list(warnings)

    log_event("OUTPUT GUARDRAIL", {"warnings": warnings})

    return {
        "final_plan": final_plan,
        "execution_log": [f"GUARDRAIL: {'OK, no issues' if not warnings else str(len(warnings)) + ' warning(s)'}"],
    }
