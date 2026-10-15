"""Risk tolerance and the typed user record (Role B).

Tolerance = the questionnaire answer stored in the user record. Language signals from the
conversation (decision model Score question) are reported alongside but, in v0, never
raise the tolerance above what the user declared. Role B can refine this.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from ...domain.agent.questions import TOLERANCE_QUESTION
from ...domain.agent.untrusted import wrap_untrusted
from ...domain.audit.events import Actor, AuditDraft, AuditKind
from ...domain.finance.profile import RiskProfile, lower_profile
from ...domain.shared.envelope import Envelope, Fact
from ...domain.shared.errors import InvalidInput
from ...domain.shared.hashing import content_id
from ...domain.user.profile import QuestionnaireAnswer, UserProfile
from ...domain.user.questionnaire import CURRENT_VERSION, REGISTRY, QuestionnaireDefinition, derive_tolerance, validate_submission
from ..conversation import UserEntry
from ..ports import AuditLog, Clock, ConversationStore, IdGenerator, ReadOnlyProfile, UserProfileStore
from ..services.decisions import DecisionService


@dataclass(frozen=True, slots=True)
class ToleranceView:
    tolerance: RiskProfile
    declared: RiskProfile | None
    language_signal: str | None
    language_confidence: float | None
    source: str


@dataclass(frozen=True, slots=True)
class UserProfileView:
    user_id: str
    display_name: dict[str, str]
    language: str
    declared_tolerance: RiskProfile | None
    questionnaire_version: str | None
    questionnaire: tuple[QuestionnaireAnswer, ...]

    @classmethod
    def from_profile(cls, profile: UserProfile) -> UserProfileView:
        return cls(
            profile.user_id, wrap_untrusted(profile.display_name), profile.language,
            profile.declared_tolerance, profile.questionnaire_version, profile.questionnaire,
        )


class ProfileUseCases:
    def __init__(self, profiles: UserProfileStore, decisions: DecisionService, conversations: ConversationStore, params_version: str) -> None:
        self._profiles = profiles
        self._decisions = decisions
        self._conversations = conversations
        self._version = params_version

    def user_profile(self, user_id: str) -> Envelope[UserProfileView]:
        profile = self._profiles.get(user_id)
        if profile is None:
            return Envelope.insufficient(("user_profile",), params_version=self._version, message="no user record")
        return Envelope.success(UserProfileView.from_profile(profile), params_version=self._version, snapshot_id=content_id("user", profile), as_of="n/a")

    def questionnaire(self) -> Envelope[QuestionnaireDefinition]:
        definition = REGISTRY[CURRENT_VERSION]
        return Envelope.success(definition, params_version=self._version, snapshot_id=content_id("questionnaire", definition), as_of="n/a")

    def risk_tolerance(self, user_id: str, session_id: str) -> Envelope[ToleranceView]:
        profile = self._profiles.get(user_id)
        declared = profile.declared_tolerance if profile else None
        recent = " ".join(e.text for e in self._conversations.history(user_id, session_id) if isinstance(e, UserEntry))[-2000:]
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


class ProfileEditing:
    def __init__(self, profiles: UserProfileStore, audit: AuditLog, clock: Clock, ids: IdGenerator, params_version: str) -> None:
        self._profiles = profiles
        self._audit = audit
        self._clock = clock
        self._ids = ids
        self._version = params_version

    def _save(self, profile: UserProfile, session_id: str, detail: str) -> Envelope[UserProfileView]:
        try:
            self._profiles.put(profile)
        except ReadOnlyProfile:
            return Envelope.invalid("user_id", (), params_version=self._version, message="profile is read-only")
        self._audit.append(AuditDraft(
            event_id=self._ids.new("evt"), timestamp=self._clock.now(), session_id=session_id,
            user_id=profile.user_id, actor=Actor.USER, kind=AuditKind.PROFILE_UPDATED, detail=detail,
        ))
        return Envelope.success(
            UserProfileView.from_profile(profile), params_version=self._version,
            snapshot_id=content_id("user", profile), as_of="n/a",
        )

    def update_profile(self, user_id: str, session_id: str, *, display_name: str | None = None, language: str | None = None) -> Envelope[UserProfileView]:
        current = self._profiles.get(user_id)
        if current is None:
            return Envelope.insufficient(("user_profile",), params_version=self._version, message="no user record")
        try:
            updated = replace(
                current,
                display_name=display_name if display_name is not None else current.display_name,
                language=language if language is not None else current.language,
            )
        except InvalidInput as error:
            return Envelope.invalid(error.field, error.allowed, params_version=self._version, message=error.message)
        fields = tuple(field for field, value in (("display_name", display_name), ("language", language)) if value is not None)
        if not fields:
            return Envelope.invalid("profile", (), params_version=self._version, message="no fields to update")
        return self._save(updated, session_id, f"fields={','.join(fields)}")

    def submit_questionnaire(
        self, user_id: str, session_id: str, version: str, answers: Sequence[QuestionnaireAnswer]
    ) -> Envelope[UserProfileView]:
        current = self._profiles.get(user_id)
        if current is None:
            return Envelope.insufficient(("user_profile",), params_version=self._version, message="no user record")
        try:
            valid = validate_submission(version, answers)
            tolerance = derive_tolerance(version, valid)
            updated = replace(current, questionnaire_version=version, questionnaire=valid, declared_tolerance=tolerance)
        except InvalidInput as error:
            return Envelope.invalid(error.field, error.allowed, params_version=self._version, message=error.message)
        return self._save(updated, session_id, f"fields=questionnaire;version={version};tolerance={tolerance.value}")
