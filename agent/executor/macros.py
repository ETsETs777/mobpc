import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MacroRunner:
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        from executor.dispatcher import dispatcher

        name = payload.get("name", "unnamed")
        steps = payload.get("steps", [])
        results = []
        for i, step in enumerate(steps):
            cmd_type = step.get("type")
            step_payload = step.get("payload", {})
            delay = float(step.get("delay", 0))
            if not cmd_type:
                continue
            try:
                result = await dispatcher.dispatch(cmd_type, step_payload, "macro")
                results.append({"step": i, "type": cmd_type, "ok": True, "data": result})
            except Exception as exc:
                results.append({"step": i, "type": cmd_type, "ok": False, "error": str(exc)})
                logger.warning("Macro step %d failed: %s", i, exc)
            if delay > 0:
                await asyncio.sleep(delay)
        return {"name": name, "steps_run": len(results), "results": results}


macro_runner = MacroRunner()
