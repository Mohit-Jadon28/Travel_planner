
from __future__ import annotations

import json
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from travel_planner.agents import SUBAGENT_SPAWN_LOG
from travel_planner.config import require_keys
from travel_planner.graph import build_app
from travel_planner.guardrails import input_guardrail
from travel_planner.memory_store import MEMORY
from travel_planner.pdf_export import markdown_plan_to_pdf
from travel_planner.resource_manager import ResourceManager
from travel_planner.sandbox import SANDBOX_ROOT
from travel_planner.schemas import TravelRequest
from travel_planner.utils import configure_console_encoding


ProgressCallback = Callable[[str, dict[str, Any]], None]


def run_trip(
    request: TravelRequest,
    *,
    force_refresh: bool = False,
    thread_id: str | None = None,
    output_dir: str | Path | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the graph and return a UI-friendly result bundle."""
    configure_console_encoding()
    problems = require_keys()
    if problems:
        raise RuntimeError("; ".join(problems))

    warnings = list(input_guardrail(request))
    ResourceManager.reset_run_budget()
    SUBAGENT_SPAWN_LOG.clear()

    app = build_app()
    thread_id = thread_id or f"ui_{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "user_id": "ui_user",
        "request": request.model_dump(),
        "plan": {},
        "skill_context": "",
        "force_refresh": force_refresh,
        "flight_results": {},
        "hotel_results": {},
        "food_results": {},
        "attraction_results": {},
        "transport_results": {},
        "budget_result": {},
        "optimization_rounds": 0,
        "critique_result": {},
        "critique_rounds": 0,
        "final_plan": {},
        "errors": [],
        "execution_log": [],
        "resource_usage": [],
        "loop_trace": [],
    }

    for event in app.stream(initial_state, config=config, stream_mode="updates"):
        for node_name, update in event.items():
            if progress:
                progress(node_name, update)

    result = dict(app.get_state(config).values)
    result["input_warnings"] = warnings
    result["subagents_spawned"] = list(SUBAGENT_SPAWN_LOG)
    result["sandbox_root"] = str(SANDBOX_ROOT)
    result["thread_id"] = thread_id

    totals = defaultdict(lambda: {"tool_calls": 0, "llm_calls": 0, "llm_failures": 0, "tokens": 0})
    for usage in result.get("resource_usage", []):
        agent = usage["agent"]
        totals[agent]["tool_calls"] += usage.get("tool_calls_used", 0)
        totals[agent]["llm_calls"] += usage.get("llm_calls_used", 0)
        totals[agent]["llm_failures"] += usage.get("llm_failures", 0)
        totals[agent]["tokens"] += usage.get("total_tokens", 0)
    result["token_totals_by_agent"] = dict(totals)
    result["total_llm_calls"] = sum(item["llm_calls"] for item in totals.values())
    result["total_tool_calls"] = sum(item["tool_calls"] for item in totals.values())
    result["total_tokens"] = sum(item["tokens"] for item in totals.values())

    destination = Path(output_dir or tempfile.mkdtemp(prefix="travel-planner-"))
    destination.mkdir(parents=True, exist_ok=True)
    report = {
        "request": result["request"],
        "budget_result": result.get("budget_result", {}),
        "critique_result": result.get("critique_result", {}),
        "guardrail_warnings": result.get("final_plan", {}).get("guardrail_warnings", []),
        "input_warnings": warnings,
        "resource_usage": result.get("resource_usage", []),
        "token_totals_by_agent": result["token_totals_by_agent"],
        "execution_log": result.get("execution_log", []),
        "loop_trace": result.get("loop_trace", []),
        "errors": result.get("errors", []),
    }
    report_path = destination / "run_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    plan_text = result.get("final_plan", {}).get("travel_plan", "")
    pdf_path = destination / "travel_plan.pdf"
    markdown_plan_to_pdf(
        plan_text,
        result.get("budget_result", {}),
        result["request"],
        result.get("resource_usage", []),
        report["guardrail_warnings"],
        str(pdf_path),
    )
    result["report_path"] = str(report_path)
    result["pdf_path"] = str(pdf_path)
    return result
