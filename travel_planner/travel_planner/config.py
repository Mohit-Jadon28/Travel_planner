
from __future__ import annotations

import os
from dotenv import load_dotenv

# Load .env from the current working directory (or nearest parent) if present.
load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

CONFIG = {
    "model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
    "temperature": float(os.environ.get("GROQ_TEMPERATURE", "0.2")),
    "max_tokens": int(os.environ.get("GROQ_MAX_TOKENS", "1200")),
    "max_total_llm_calls": int(os.environ.get("TRAVEL_MAX_LLM_CALLS", "10")),

    # Per-agent resource harness: hard ceilings on tool calls / retries / input
    # tokens so a single agent can never blow the whole run's token budget.
    "resource_budgets": {
        "orchestrator": {"max_tool_calls": 0, "max_llm_retries": 0, "max_input_tokens": 700},
        "flight":        {"max_tool_calls": 1, "max_llm_retries": 0, "max_input_tokens": 700},
        "hotel":         {"max_tool_calls": 1, "max_llm_retries": 0, "max_input_tokens": 700},
        "food":          {"max_tool_calls": 1, "max_llm_retries": 0, "max_input_tokens": 700},
        "attraction":    {"max_tool_calls": 2, "max_llm_retries": 0, "max_input_tokens": 800},
        "transport":     {"max_tool_calls": 1, "max_llm_retries": 0, "max_input_tokens": 700},
        "budget":        {"max_tool_calls": 0, "max_llm_retries": 0, "max_input_tokens": 900},
        "optimizer":     {"max_tool_calls": 0, "max_llm_retries": 0, "max_input_tokens": 700},
        "critic":        {"max_tool_calls": 0, "max_llm_retries": 0, "max_input_tokens": 900},
        "final":         {"max_tool_calls": 0, "max_llm_retries": 0, "max_input_tokens": 1200},
    },

    "max_optimization_rounds": 1,
    "max_critique_rounds": 1,
    "retry": {"max_attempts": 1, "base_delay": 1.5},

    # Aggressive compression settings keep prompts small -> fewer tokens billed
    # per call, which matters a lot on free-tier rate limits.
    "compression": {
        "search_results_kept": 3,
        "search_snippet_chars": 220,
        "prior_state_chars": 700,
        "skill_excerpt_chars": 900,
        "weather_chars": 260,
    },

    "guardrails": {
        "min_budget_per_day_per_person": 300,
        "max_budget_per_day_per_person": 100000,
        "max_days": 30,
        "max_travelers": 20,
        "max_notes_chars": 500,
        "max_reference_file_bytes": 5 * 1024 * 1024,
        "max_output_chars": 14000,
        "banned_keywords": [
            "smuggl", "human traffick", "drug traffic", "buy weapon",
            "fake passport", "counterfeit document", "bribe official",
            "illegal border cross",
        ],
        "injection_patterns": [
            r"ignore (all )?previous instructions",
            r"disregard (the )?system prompt",
            r"you are now (a|an) ",
            r"reveal (your )?(system|hidden) prompt",
        ],
    },

    # Sandbox root that all file read/write/shell tools are jailed to.
    "sandbox_dir": os.environ.get("TRAVEL_SANDBOX_DIR", os.path.join(os.getcwd(), "travel_sandbox")),
    "memory_path": os.environ.get("TRAVEL_MEMORY_PATH", os.path.join(os.getcwd(), "travel_agent_memory.json")),
}

RESOURCE_CONFIG = CONFIG["resource_budgets"]
MAX_OPTIMIZATION_ROUNDS = CONFIG["max_optimization_rounds"]
MAX_CRITIQUE_ROUNDS = CONFIG["max_critique_rounds"]
COMPRESSION = CONFIG["compression"]
GUARDRAILS = CONFIG["guardrails"]


def require_keys() -> list[str]:
    """Returns a list of human-readable problems (empty if all required keys are set)."""
    problems = []
    if not GROQ_API_KEY:
        problems.append("GROQ_API_KEY is not set (copy .env.example to .env and fill it in).")
    if not TAVILY_API_KEY:
        problems.append("TAVILY_API_KEY is not set (copy .env.example to .env and fill it in).")
    return problems
