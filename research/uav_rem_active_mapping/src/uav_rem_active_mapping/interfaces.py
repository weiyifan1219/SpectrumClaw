"""Stable cross-module interfaces; implementations may evolve independently."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ReconstructionRequest:
    sparse_rss_dbm: Any  # [B,F,Z,H,W], NaN only before tensor preprocessing
    observed_mask: Any   # [B,F,Z,H,W]
    building_height_m: Any  # [B,1,H,W]
    flyable_mask: Any  # [B,Z,H,W]
    frequencies_hz: Any  # [B,F]
    heights_m: Any  # [B,Z]


@dataclass(frozen=True)
class ReconstructionResult:
    mean_dbm: Any  # [B,F,Z,H,W]
    scale_db: Any  # [B,F,Z,H,W], Laplace predictive scale b (std=sqrt(2)*b)
    # Current model does not identify separate epistemic/aleatoric components.


class Reconstructor(Protocol):
    def predict(self, request: ReconstructionRequest) -> ReconstructionResult: ...


@dataclass(frozen=True)
class CandidateSet:
    positions_enu_m: Any  # [K,3]
    action_mask: Any  # [K+1], final entry is STOP
    path_cost_m: Any  # [K]
    feature_vectors: Any  # [K,D]


class CandidatePolicy(Protocol):
    def select(self, belief: ReconstructionResult, candidates: CandidateSet) -> int: ...


class SafetyNavigator(Protocol):
    def plan(self, start_enu_m: tuple[float, float, float], target_enu_m: tuple[float, float, float]) -> list[tuple[float, float, float]]: ...
