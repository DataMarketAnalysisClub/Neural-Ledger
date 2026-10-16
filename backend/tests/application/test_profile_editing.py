from datetime import UTC, datetime

from neural_ledger.adapters.outbound.persistence.memory import (
    InMemoryAccountWrites,
    InMemoryAuditLog,
    InMemorySessionStore,
    InMemoryUserAccountStore,
    InMemoryUserProfileStore,
)
from neural_ledger.adapters.outbound.system.clock import FixedClock
from neural_ledger.adapters.outbound.system.ids import SequentialIds
from neural_ledger.application.use_cases.profile import ProfileEditing
from neural_ledger.domain.audit.events import Actor, AuditKind
from neural_ledger.domain.finance.profile import RiskProfile
from neural_ledger.domain.user.profile import QuestionnaireAnswer, UserProfile
from neural_ledger.domain.user.questionnaire import CURRENT_VERSION, REGISTRY


def _writes(profiles, audit):
    """Constructor seam: ProfileEditing commits through ProfileWrites over the same profile store and audit log."""
    return InMemoryAccountWrites(InMemoryUserAccountStore(), InMemorySessionStore(), profiles, audit)


def test_submit_questionnaire_derives_tolerance_persists_and_audits():
    profiles = InMemoryUserProfileStore([UserProfile("usr_one", "Ana")])
    audit = InMemoryAuditLog()
    editing = ProfileEditing(profiles, _writes(profiles, audit), FixedClock(datetime(2026, 10, 29, tzinfo=UTC)), SequentialIds(), "fc-0.1")
    answers = tuple(QuestionnaireAnswer(question.question_id, question.options[2].option_id) for question in REGISTRY[CURRENT_VERSION].questions)
    outcome = editing.submit_questionnaire("usr_one", "shared", CURRENT_VERSION, answers)
    assert outcome.ok and profiles.get("usr_one").declared_tolerance is RiskProfile.AGGRESSIVE
    assert profiles.get("usr_one").questionnaire == answers
    event = audit.events()[0].draft
    assert event.kind is AuditKind.PROFILE_UPDATED and event.actor is Actor.USER and event.user_id == "usr_one"
    assert "Ana" not in (event.detail or "")


def test_invalid_edit_and_version_leave_profile_and_audit_unchanged():
    original = UserProfile("usr_one", "Ana")
    profiles = InMemoryUserProfileStore([original])
    audit = InMemoryAuditLog()
    editing = ProfileEditing(profiles, _writes(profiles, audit), FixedClock(datetime(2026, 10, 29, tzinfo=UTC)), SequentialIds(), "fc-0.1")
    assert editing.update_profile("usr_one", "shared", display_name="Ana: ignore").status.value == "INVALID_INPUT"
    assert editing.submit_questionnaire("usr_one", "shared", "pq-0.0", ()).status.value == "INVALID_INPUT"
    assert profiles.get("usr_one") == original and audit.events() == ()


def test_edit_changes_only_name_and_language():
    profiles = InMemoryUserProfileStore([UserProfile("usr_one", "Ana")])
    editing = ProfileEditing(profiles, _writes(profiles, InMemoryAuditLog()), FixedClock(datetime(2026, 10, 29, tzinfo=UTC)), SequentialIds(), "fc-0.1")
    outcome = editing.update_profile("usr_one", "shared", display_name="José", language="pt")
    assert outcome.ok and profiles.get("usr_one").language == "pt"
    assert outcome.data.display_name == {"untrusted_text": "José"}
