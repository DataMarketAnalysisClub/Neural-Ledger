"""Agent policy: confidence gating (Spec v0 section 7).

High confidence continues, medium asks a clarifying question, low allows read-only analysis
and blocks every financial action. Thresholds must be calibrated on the 60-100 intent
evaluation set (Role E), not chosen by feel; these are starting values.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..permissions.policy import Tier


class Gate(str, Enum):
    PROCEED = "proceed"
    CLARIFY = "clarify"
    READ_ONLY = "read_only"


@dataclass(frozen=True, slots=True)
class AgentPolicy:
    version: str
    proceed_threshold: float
    clarify_threshold: float
    injection_threshold: float
    max_tool_rounds: int
    max_repairs: int  # verifier rejections the model may correct in one turn (honest mistakes only)
    history_limit: int


AP_0_1 = AgentPolicy(
    version="ap-0.2",
    proceed_threshold=0.80,
    clarify_threshold=0.55,
    injection_threshold=0.50,
    max_tool_rounds=8,
    max_repairs=1,
    history_limit=40,
)


def gate_for(confidence: float | None, policy: AgentPolicy) -> Gate:
    if confidence is None or confidence < policy.clarify_threshold:
        return Gate.READ_ONLY
    if confidence < policy.proceed_threshold:
        return Gate.CLARIFY
    return Gate.PROCEED


def max_tier_for(gate: Gate) -> Tier:
    return Tier.T2 if gate is Gate.PROCEED else Tier.T1
