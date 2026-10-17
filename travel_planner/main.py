
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from travel_planner.config import require_keys
from travel_planner.schemas import TravelRequest
from travel_planner.guardrails import input_guardrail
from travel_planner.memory_store import MEMORY
from travel_planner.sandbox import SANDBOX_ROOT
from travel_planner.graph import build_app
from travel_planner.agents import SUBAGENT_SPAWN_LOG
from travel_planner.pdf_export import markdown_plan_to_pdf
from travel_planner.utils import configure_console_encoding
from travel_planner.resource_manager import ResourceManager


EXAMPLE_REQUEST = {
    "origin": "Delhi",
    "destination": "Vadodara",
    "total_budget": 40000,
    "currency": "INR",
    "display_currency": None,
    "travelers": 2,
    "days": 3,
    "travel_style": "balanced",
    "hotel_preference": "comfortable",
    "food_preference": "mixed",
    "interests": ["history", "museums", "local food", "malls"],
    "notes": "Prefer vegetarian food options, would like at least one half-day "
             "dedicated to museums, and would appreciate hotels within walking "
             "distance of the old city center if possible.",
    "reference_files": [],
}


def sanity_check() -> bool:
    problems = require_keys()
    if problems:
        print("\u26a0\ufe0f  Fix these before running the graph:")
        for p in problems:
            print("  -", p)
        return False
    print(" Environment looks good")
    return True


def load_request(config_path: str | None, reference_files: list[str]) -> TravelRequest:
    if config_path:
        config_file = Path(config_path).resolve()
        data = json.loads(config_file.read_text())
        base_dir = config_file.parent
    else:
        data = dict(EXAMPLE_REQUEST)
        base_dir = Path.cwd()

    configured_references = data.get("reference_files", [])
    all_references = configured_references + reference_files
    data["reference_files"] = [
        str((base_dir / path).resolve()) if not Path(path).is_absolute() else path
        for path in all_references
    ]
    return TravelRequest(**data)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the multi-agent travel planner.")
    p.add_argument("--config", type=str, default=None, help="Path to a JSON file describing the TravelRequest.")
    p.add_argument("--reference-file", action="append", default=[], dest="reference_files",
                   help="Reference file to ground the plan; repeat for multiple files.")
    p.add_argument("--out-dir", type=str, default=".", help="Directory to write travel_plan.pdf and run_report.json.")
    p.add_argument("--clear-memory", action="store_true", help="Wipe the on-disk token-saving cache before running.")
    p.add_argument("--fresh-run", action="store_true",
                   help="Force every subagent and Tavily search to call live services; bypass caches.")
    p.add_argument("--thread-id", type=str, default="travel_session_001", help="LangGraph checkpoint thread id.")
    return p.parse_args()


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    ResourceManager.reset_run_budget()

    if not sanity_check():
        return 1

    if args.clear_memory:
        MEMORY.clear()
        print(f"Cleared persistent memory cache.")

    request = load_request(args.config, args.reference_files)

    warnings = input_guardrail(request)
    if warnings:
        print(" Input guardrail warnings (run continues, but review these):")
        for w in warnings:
            print("  -", w)
    else:
        print(" Input guardrail: no issues found.")

    print(f"Sandbox root: {SANDBOX_ROOT}")

    app = build_app()

    initial_state = {
        "user_id": "user_001",
        "request": request.model_dump(),
        "plan": {},
        "skill_context": "",
        "force_refresh": args.fresh_run,
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
    config = {"configurable": {"thread_id": args.thread_id}}

    for event in app.stream(initial_state, config=config, stream_mode="updates"):
        for node_name, update in event.items():
            print("\n" + "#" * 70)
            print(f"# COMPLETED NODE: {node_name.upper()}")
            print("#" * 70)
            for line in update.get("execution_log", []):
                print(" -", line)

    result = app.get_state(config).values

    # --- resource / token usage summary -------------------------------
    totals = defaultdict(lambda: {"tool_calls": 0, "llm_calls": 0, "llm_failures": 0, "tokens": 0})
    for u in result.get("resource_usage", []):
        totals[u["agent"]]["tool_calls"] += u.get("tool_calls_used", 0)
        totals[u["agent"]]["llm_calls"] += u.get("llm_calls_used", 0)
        totals[u["agent"]]["llm_failures"] += u.get("llm_failures", 0)
        totals[u["agent"]]["tokens"] += u.get("total_tokens", 0)

    print("\nRESOURCE / TOKEN USAGE BY AGENT")
    grand_total = 0
    for agent, t in totals.items():
        print(f"  {agent:12s}  tool_calls={t['tool_calls']}  llm_calls={t['llm_calls']}  "
              f"failures={t['llm_failures']}  tokens={t['tokens']:,}")
        grand_total += t["tokens"]

    print("\nTotal LLM calls:", sum(t["llm_calls"] for t in totals.values()))
    print("Total tool calls:", sum(t["tool_calls"] for t in totals.values()))
    print("Total tokens consumed:", f"{grand_total:,}")

    print("\nOptimization rounds used:", result.get("optimization_rounds", 0))
    print("Critique rounds used:", result.get("critique_rounds", 0))
    print("Final critic approval:", result.get("critique_result", {}).get("approved"))

    plan_warnings = result.get("final_plan", {}).get("guardrail_warnings", [])
    if plan_warnings:
        print("\n\u26a0\ufe0f  Guardrail warnings on the final output:")
        for w in plan_warnings:
            print(" -", w)
    else:
        print("\n\u2705 Output guardrail: no issues found.")

    if result.get("errors"):
        print("\n\u26a0\ufe0f Errors encountered during the run (nodes degraded gracefully):")
        for e in result["errors"]:
            print(" -", e)
    else:
        print("\nNo errors during the run.")

    print("\nSUBAGENTS SPAWNED THIS RUN:")
    if SUBAGENT_SPAWN_LOG:
        for s in SUBAGENT_SPAWN_LOG:
            print(f"  \U0001F9F5 [{s['id']}] agent={s['agent']}  spawned_at={s['ts']}")
    else:
        print("  (none \u2014 everything this run was served entirely from memory)")

    print(f"\nTotal distinct subagent spawns : {len(SUBAGENT_SPAWN_LOG)}")
    print(f"Persistent memory entries      : {len(MEMORY)}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    run_report = {
        "request": result["request"],
        "budget_result": result.get("budget_result"),
        "critique_result": result.get("critique_result"),
        "guardrail_warnings": plan_warnings,
        "resource_usage": result.get("resource_usage", []),
        "token_totals_by_agent": {k: v for k, v in totals.items()},
        "execution_log": result.get("execution_log", []),
        "loop_trace": result.get("loop_trace", []),
        "errors": result.get("errors", []),
    }
    report_path = out_dir / "run_report.json"
    report_path.write_text(json.dumps(run_report, indent=2, default=str))

    pdf_path = out_dir / "travel_plan.pdf"
    markdown_plan_to_pdf(
        result["final_plan"]["travel_plan"],
        result.get("budget_result", {}),
        result["request"],
        result.get("resource_usage", []),
        plan_warnings,
        str(pdf_path),
    )

    print(f"\nPDF saved to: {pdf_path}")
    print(f"Run report saved to: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
