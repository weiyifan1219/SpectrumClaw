"""Provider-neutral contracts for SpectrumClaw tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


ToolHandler = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class ToolExposure:
    """Select which protocol surfaces may publish a tool."""

    native: bool = True
    mcp: bool = False


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """The single source of truth for one callable capability."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    category: str = ""
    exposure: ToolExposure = field(default_factory=ToolExposure)
    timeout_s: float = 30.0
    read_only: bool = True

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
