
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import CONFIG

SANDBOX_ROOT = Path(CONFIG["sandbox_dir"]).resolve()
SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)

ALLOWED_SHELL_CMDS = {"ls", "cat", "wc", "find", "echo", "pwd", "date", "mkdir", "mv", "cp"}
EXEC_LOG: list[dict[str, Any]] = []


def _within_sandbox(path_str: str) -> Path:
    p = (SANDBOX_ROOT / path_str).resolve() if not path_str.startswith("/") else Path(path_str).resolve()
    if p != SANDBOX_ROOT and SANDBOX_ROOT not in p.parents:
        raise PermissionError(f"Path '{path_str}' escapes the sandbox root {SANDBOX_ROOT}")
    return p


def run_shell(command: str) -> str:
    """Run an allow-listed shell command inside the sandbox. Everything else is blocked."""
    first_word = command.strip().split(" ")[0] if command.strip() else ""
    entry: dict[str, Any] = {"ts": datetime.now().isoformat(timespec="seconds"), "command": command}
    if first_word not in ALLOWED_SHELL_CMDS:
        entry["result"] = f"BLOCKED (not in allowlist: {sorted(ALLOWED_SHELL_CMDS)})"
        EXEC_LOG.append(entry)
        print(f"   \U0001F5A5\uFE0F  $ {command}  ->  \u26D4 blocked")
        return entry["result"]
    try:
        proc = subprocess.run(
            command, shell=True, cwd=SANDBOX_ROOT, capture_output=True, text=True, timeout=10
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        entry["result"] = out[:1500]
        entry["exit_code"] = proc.returncode
        EXEC_LOG.append(entry)
        print(f"   \U0001F5A5\uFE0F  $ {command}  ->  exit={proc.returncode}")
        return entry["result"] or "(no output)"
    except Exception as e:  # noqa: BLE001
        entry["result"] = f"ERROR: {e}"
        EXEC_LOG.append(entry)
        print(f"   \U0001F5A5\uFE0F  $ {command}  ->  \u26A0\uFE0F {e}")
        return entry["result"]


def read_file_from_sandbox(path: str) -> str:
    p = _within_sandbox(path)
    if not p.exists() or not p.is_file():
        return f"ERROR: '{path}' not found in sandbox."
    text = p.read_text(encoding="utf-8", errors="ignore")
    print(f"   \U0001F4C4 read_file('{path}') -> {len(text)} chars")
    return text


def write_file_to_sandbox(path: str, content: str) -> str:
    p = _within_sandbox(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"   \u270D\uFE0F  write_file('{path}') -> {len(content)} chars written")
    return f"Wrote {len(content)} chars to {path}"
