import ctypes
from typing import Any


class InputBlocker:
    def __init__(self) -> None:
        self._blocked = False
        self._hook = None

    def set_blocked(self, payload: dict[str, Any]) -> dict[str, Any]:
        enabled = payload.get("enabled", True)
        self._blocked = enabled
        # BlockInput requires admin; best-effort
        try:
            ctypes.windll.user32.BlockInput(enabled)
        except Exception:
            pass
        return {"blocked": self._blocked}


input_blocker = InputBlocker()
