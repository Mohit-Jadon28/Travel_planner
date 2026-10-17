
from __future__ import annotations

import json
import random
import time
from typing import Any, Callable

from .config import CONFIG

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        if not text:
            return 0
        return len(_ENC.encode(text))
except Exception:
    def count_tokens(text: str) -> int:
        # ~4 chars/token fallback if tiktoken isn't available.
        return max(1, len(text or "") // 4)


def call_with_retry(fn: Callable, *args, max_attempts: int | None = None,
                     base_delay: float | None = None, **kwargs) -> Any:
    """Exponential-backoff retry harness used for every network/LLM call."""
    max_attempts = max_attempts or CONFIG["retry"]["max_attempts"]
    base_delay = base_delay if base_delay is not None else CONFIG["retry"]["base_delay"]
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - deliberately broad, this is a generic harness
            last_exc = e
            if attempt == max_attempts:
                break
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            print(f"  [retry] attempt {attempt}/{max_attempts} failed ({e}); retrying in {delay:.1f}s")
            time.sleep(delay)
    raise last_exc


def truncate_json(obj: Any, max_chars: int) -> str:
    try:
        s = json.dumps(obj, default=str)
    except TypeError:
        s = str(obj)
    return s if len(s) <= max_chars else s[:max_chars] + "...(truncated)"


def log_event(title: str, payload: Any = None, max_chars: int = 900) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    if payload is not None:
        try:
            print(json.dumps(payload, indent=2, default=str)[:max_chars])
        except TypeError:
            print(str(payload)[:max_chars])
