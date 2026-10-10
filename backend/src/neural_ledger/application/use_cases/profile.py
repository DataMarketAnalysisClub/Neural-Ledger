"""Risk tolerance and the typed user record (Role B).

Tolerance = the questionnaire answer stored in the user record. Language signals from the
conversation (decision model Score question) are reported alongside but, in v0, never
raise the tolerance above what the user declared. Role B can refine this.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.agent.questions import TOLERANCE_QUESTION
from ...domain.finance.profile import RiskProfile, lower_profile
from ...domain.shared.envelope import Envelope, Fact
from ...domain.shared.hashing import content_id
from ...domain.user.profile import UserProfile
from ..conversation import UserEntry
from ..ports import ConversationStore, UserProfileStore
from ..services.decisions import DecisionService


@dataclass(frozen=True, slots=True)
class ToleranceView:
    tolerance: RiskProfile
    declared: RiskProfile | None
    language_signal: str | None
    language_confidence: float | None
    source: str


class ProfileUseCases:
    def __init__(self, profiles: UserProfileStore, decisions: DecisionService, conversations: ConversationStore, params_version: str) -> None:
        self._profiles = profiles
        self._decisions = decisions
        self._conversations = conversations
        self._version = params_version

    def user_profile(self, user_id: str) -> Envelope[UserProfile]:
        profile = self._profiles.get(user_id)
        if profile is None:
            return Envelope.insufficient(("user_profile",), params_version=self._version, message="no user record")
        return Envelope.success(profile, params_version=self._version, snapshot_id=content_id("user", profile), as_of="n/a")

    def risk_tolerance(self, user_id: str, session_id: str) -> Envelope[ToleranceView]:
        profile = self._profiles.get(user_id)
        declared = profile.declared_tolerance if profile else None
        recent = " ".join(e.text for e in self._conversations.history(session_id) if isinstance(e, UserEntry))[-2000:]
        signal, confidence, source = None, None, "questionnaire"
        if recent.strip():
            outcome = self._decisions.judge(recent, (TOLERANCE_QUESTION,))
            judgment = outcome.judgments.get(TOLERANCE_QUESTION.key)
            if judgment is not None:
                signal, confidence = judgment.label, judgment.confidence
        if declared is None:
            tolerance = RiskProfile.CONSERVATIVE
            source = "default (no questionnaire answer)"
            if signal and confidence and confidence >= 0.8:
                tolerance = lower_profile(RiskProfile.parse(signal), RiskProfile.MODERATE)
                source = "language signal, capped at moderate"
        else:
            tolerance = declared
        view = ToleranceView(tolerance, declared, signal, confidence, source)
        facts = (Fact("profile.tolerance", tolerance.value, "profile", source),)
        return Envelope.success(
            view, params_version=self._version, snapshot_id=content_id("tolerance", user_id, view), as_of="n/a", facts=facts
        )
