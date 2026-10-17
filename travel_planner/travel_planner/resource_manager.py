
from __future__ import annotations

from typing import Any
from threading import Lock

from .config import CONFIG
from .utils import count_tokens


class ResourceManager:
    _run_lock = Lock()
    _run_llm_calls = 0

    @classmethod
    def reset_run_budget(cls) -> None:
        with cls._run_lock:
            cls._run_llm_calls = 0

    @classmethod
    def reserve_run_llm_call(cls) -> bool:
        with cls._run_lock:
            if cls._run_llm_calls >= CONFIG["max_total_llm_calls"]:
                return False
            cls._run_llm_calls += 1
            return True

    def __init__(self, agent_name: str, max_tool_calls: int = 0,
                 max_llm_retries: int = 2, max_input_tokens: int = 900):
        self.agent_name = agent_name
        self.max_tool_calls = max_tool_calls
        self.max_llm_retries = max_llm_retries
        self.max_input_tokens = max_input_tokens
        self.tool_calls_used = 0
        self.llm_calls_used = 0
        self.retries_used = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.llm_failures = 0
        self.last_error = ""
        self.run_limit_hits = 0

    def reserve_llm_call(self) -> bool:
        allowed = self.reserve_run_llm_call()
        if not allowed:
            self.run_limit_hits += 1
            self.last_error = f"run LLM limit ({CONFIG['max_total_llm_calls']}) reached"
        return allowed

    def can_use_tool(self) -> bool:
        return self.tool_calls_used < self.max_tool_calls

    def use_tool(self) -> None:
        self.tool_calls_used += 1

    def enforce_input_budget(self, prompt: str) -> str:
        toks = count_tokens(prompt)
        if toks <= self.max_input_tokens:
            return prompt
        ratio = self.max_input_tokens / max(1, toks)
        cut = max(200, int(len(prompt) * ratio * 0.95))
        return prompt[:cut] + "\n[...context trimmed to fit the agent's token budget...]"

    def record_llm_call(self, prompt: str, response_text: str) -> None:
        self.llm_calls_used += 1
        self.input_tokens += count_tokens(prompt)
        self.output_tokens += count_tokens(response_text)

    def record_llm_failure(self, prompt: str, error: str) -> None:
        self.llm_failures += 1
        self.last_error = error[:500]
        self.input_tokens += count_tokens(prompt)

    def summary(self) -> dict[str, Any]:
        return {
            "agent": self.agent_name,
            "tool_calls_used": self.tool_calls_used,
            "llm_calls_used": self.llm_calls_used,
            "retries_used": self.retries_used,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "llm_failures": self.llm_failures,
            "last_error": self.last_error,
            "run_limit_hits": self.run_limit_hits,
        }
