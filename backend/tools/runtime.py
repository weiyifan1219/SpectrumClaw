"""One execution path shared by native and protocol adapters."""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

from .contracts import ToolSpec


class ToolValidationError(ValueError):
    pass


def _matches_type(value: Any, expected: str) -> bool:
    checks = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "null": lambda item: item is None,
    }
    check = checks.get(expected)
    return True if check is None else check(value)


def validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> None:
    """Validate the JSON-Schema subset used by SpectrumClaw tool contracts."""
    schema = spec.parameters
    required = schema.get("required", [])
    for name in required:
        if name not in arguments:
            raise ToolValidationError(f"Missing required argument: {name}")

    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        unexpected = set(arguments) - set(properties)
        if unexpected:
            raise ToolValidationError(f"Unexpected argument: {sorted(unexpected)[0]}")

    for name, value in arguments.items():
        rule = properties.get(name)
        if not rule:
            continue
        expected = rule.get("type")
        if expected and not _matches_type(value, expected):
            raise ToolValidationError(f"Argument {name} must be {expected}")
        if "enum" in rule and value not in rule["enum"]:
            raise ToolValidationError(f"Argument {name} must be one of {rule['enum']}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in rule and value < rule["minimum"]:
                raise ToolValidationError(f"Argument {name} must be >= {rule['minimum']}")
            if "maximum" in rule and value > rule["maximum"]:
                raise ToolValidationError(f"Argument {name} must be <= {rule['maximum']}")
        if isinstance(value, str):
            if "minLength" in rule and len(value) < rule["minLength"]:
                raise ToolValidationError(f"Argument {name} is too short")
            if "maxLength" in rule and len(value) > rule["maxLength"]:
                raise ToolValidationError(f"Argument {name} is too long")


class ToolRuntime:
    def __init__(self, registry: dict[str, ToolSpec] | None = None) -> None:
        if registry is None:
            from .registry import TOOL_REGISTRY
            registry = TOOL_REGISTRY
        self._registry = registry

    def get_spec(self, name: str) -> ToolSpec | None:
        return self._registry.get(name)

    async def invoke(self, name: str, arguments: dict[str, Any], *, surface: str = "native") -> Any:
        spec = self.get_spec(name)
        if spec is None:
            raise LookupError(f"Unknown tool: {name}")
        if surface not in {"native", "mcp"}:
            raise ValueError(f"Unknown tool surface: {surface}")
        if not getattr(spec.exposure, surface):
            raise PermissionError(f"Tool is not available on the {surface} surface: {name}")
        validate_arguments(spec, arguments)

        if inspect.iscoroutinefunction(spec.handler):
            return await asyncio.wait_for(spec.handler(**arguments), timeout=spec.timeout_s)
        if spec.read_only:
            result = await asyncio.wait_for(
                asyncio.to_thread(spec.handler, **arguments),
                timeout=spec.timeout_s,
            )
        else:
            # Side-effecting sync calls stay on their owning thread; Python
            # cannot safely cancel a worker thread after a timeout response.
            result = spec.handler(**arguments)
        if inspect.isawaitable(result):
            return await asyncio.wait_for(result, timeout=spec.timeout_s)
        return result

    async def execute_json(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            result = await self.invoke(name, arguments)
        except LookupError as exc:
            return json.dumps({"error": str(exc), "code": "tool_not_found"}, ensure_ascii=False)
        except asyncio.TimeoutError:
            return json.dumps(
                {"error": f"Tool timed out after {self._registry[name].timeout_s:g}s", "code": "tool_timeout", "tool": name},
                ensure_ascii=False,
            )
        except ToolValidationError as exc:
            return json.dumps(
                {"error": str(exc), "code": "tool_validation_error", "tool": name},
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {"error": str(exc), "code": "tool_execution_error", "tool": name},
                ensure_ascii=False,
            )

        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)
