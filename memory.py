"""Local persistence for the bot: per-user Letta agent IDs and processed notifications.

This is a tiny JSON-backed store, good enough for a single bot process.
If you ever run multiple bot instances against the same account, swap this
for SQLite or a real database.
"""

import json
import threading
from pathlib import Path
from typing import Optional


class BotState:
    def __init__(self, path: str):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._data = {"agents": {}, "seen": []}
        if self._path.exists():
            self._data = json.loads(self._path.read_text())
            self._data.setdefault("agents", {})
            self._data.setdefault("seen", [])

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data, indent=2))

    def get_agent_id(self, did: str) -> Optional[str]:
        return self._data["agents"].get(did)

    def save_agent_id(self, did: str, agent_id: str) -> None:
        with self._lock:
            self._data["agents"][did] = agent_id
            self._save()

    def has_seen(self, uri: str) -> bool:
        return uri in self._data["seen"]

    def mark_seen(self, uri: str) -> None:
        with self._lock:
            self._data["seen"].append(uri)
            # keep the file from growing forever
            self._data["seen"] = self._data["seen"][-5000:]
            self._save()
