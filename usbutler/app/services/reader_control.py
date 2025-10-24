import json
import os
import threading
import time
from typing import Dict, Optional


class ReaderControl:
    """Coordinates exclusive access to the NFC reader between services."""

    def __init__(self, state_file: Optional[str] = None, default_owner: str = "door") -> None:
        self.state_file = state_file or os.getenv("USBUTLER_READER_STATE_FILE", "reader_state.json")
        self.default_owner = default_owner
        self._lock = threading.Lock()

    def _ensure_directory(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.state_file)) or "."
        os.makedirs(directory, exist_ok=True)

    def _read_state_unlocked(self) -> Dict[str, object]:
        try:
            with open(self.state_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict) and "owner" in data:
                    return data
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError):
            pass
        return {"owner": self.default_owner, "updated_at": None}

    def get_state(self) -> Dict[str, object]:
        with self._lock:
            return self._read_state_unlocked()

    def get_owner(self) -> str:
        return str(self.get_state().get("owner", self.default_owner))

    def set_owner(self, owner: str, metadata: Optional[Dict[str, object]] = None) -> Dict[str, object]:
        with self._lock:
            self._ensure_directory()
            state: Dict[str, object] = {"owner": owner, "updated_at": time.time()}
            if metadata:
                state.update(metadata)
            temp_path = f"{self.state_file}.tmp"
            with open(temp_path, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
            os.replace(temp_path, self.state_file)
            return state

    def reset_to_default(self) -> Dict[str, object]:
        return self.set_owner(self.default_owner)


__all__ = ["ReaderControl"]
