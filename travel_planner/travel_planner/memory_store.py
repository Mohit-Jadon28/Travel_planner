
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from .config import CONFIG


class MemoryStore:
    def __init__(self, path: str | None = None):
        self.path = Path(path or CONFIG["memory_path"])
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2, default=str))

    def fingerprint(self, *parts: Any) -> str:
        raw = "||".join(str(p) for p in parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, key: str) -> Optional[Any]:
        val = self._data.get(key)
        print(f"   \U0001F9E0 memory lookup '{key}' -> "
              f"{'HIT (reused, 0 tokens)' if val is not None else 'miss'}")
        return val

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._save()

    def clear(self) -> None:
        self._data = {}
        if self.path.exists():
            self.path.unlink()

    def __len__(self) -> int:
        return len(self._data)


# Module-level singleton used across the app.
MEMORY = MemoryStore()
