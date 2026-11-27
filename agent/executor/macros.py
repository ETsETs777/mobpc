import asyncio
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# Внутри макроса нельзя запускать другой макрос или стрим — защита от рекурсии.
_FORBIDDEN_IN_MACRO = {"macro.run", "screen.stream"}
_MAX_STEPS = 100


class MacroRunner:
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        from executor.dispatcher import dispatcher

        name = payload.get("name", "unnamed")
        steps = payload.get("steps", [])
        if not isinstance(steps, list) or len(steps) > _MAX_STEPS:
            raise ValueError(f"Макрос должен содержать не больше {_MAX_STEPS} шагов")
        validated = []
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("Шаг макроса должен быть объектом")
            cmd_type = step.get("type")
            step_payload = step.get("payload", {})
            if not isinstance(cmd_type, str) or not cmd_type.strip():
                raise ValueError("У шага макроса должен быть тип команды")
            if not isinstance(step_payload, dict):
                raise ValueError("Параметры шага макроса должны быть объектом")
            try:
                delay = float(step.get("delay", 0))
            except (ValueError, TypeError) as exc:
                raise ValueError("Некорректная задержка шага макроса") from exc
            if not math.isfinite(delay) or delay < 0:
                raise ValueError("Задержка шага макроса должна быть конечным неотрицательным числом")
            validated.append((cmd_type, step_payload, min(delay, 30.0)))
        results = []
        for i, (cmd_type, step_payload, delay) in enumerate(validated):
            if cmd_type in _FORBIDDEN_IN_MACRO:
                results.append({"step": i, "type": cmd_type, "ok": False, "error": "not allowed in macro"})
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
