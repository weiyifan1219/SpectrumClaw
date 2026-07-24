"""Public audit events for UAV operations.

Events are deliberately compact and explain observable actions and safety
decisions.  They are not a container for hidden model reasoning.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AuditEventType = Literal[
    "intent",
    "policy_decision",
    "tool_call",
    "observation",
    "run_started",
    "interruption",
    "completion",
    "error",
]


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: AuditEventType
    summary: str = Field(min_length=1, max_length=480)
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "summary": self.summary,
            "data": self.data,
            "timestamp": self.timestamp,
        }
