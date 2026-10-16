from dataclasses import replace

import pytest

from neural_ledger.adapters.outbound.persistence.memory import InMemoryUserProfileStore
from neural_ledger.adapters.outbound.persistence.overlay import PersonaOverlayProfileStore
from neural_ledger.adapters.outbound.persistence.sqlite import SqliteDatabase, SqliteUserProfileStore
from neural_ledger.application.ports import ReadOnlyProfile
from neural_ledger.domain.finance.profile import RiskProfile
from neural_ledger.domain.user.profile import QuestionnaireAnswer, UserProfile


def test_overlay_personas_win_reads_and_refuse_writes():
    original = UserProfile("camila", "Camila")
    inner = InMemoryUserProfileStore([replace(original, display_name="Other")])
    store = PersonaOverlayProfileStore((original,), inner)
    assert store.get("camila") == original
    with pytest.raises(ReadOnlyProfile):
        store.put(replace(original, display_name="Changed"))
    assert store.get("camila") == original
    ordinary = UserProfile("usr_one", "Ana")
    store.put(ordinary)
    assert store.get("usr_one") == ordinary


def test_sqlite_round_trip_upsert_and_additive_table(tmp_path):
    path = tmp_path / "profile.db"
    db = SqliteDatabase(path)
    db.connection.execute("INSERT INTO proposals VALUES (?, ?, ?)", ("p", "s", "{}"))
    profile = UserProfile("usr_one", "Ana", declared_tolerance=RiskProfile.MODERATE, questionnaire_version="pq-0.1", questionnaire=(
        QuestionnaireAnswer("set_aside", "about_half"), QuestionnaireAnswer("tight_month", "keep_cut_elsewhere"),
        QuestionnaireAnswer("goal_vs_room", "balance"), QuestionnaireAnswer("surprise", "uneasy_but_ok"),
        QuestionnaireAnswer("habit", "sometimes"),
    ))
    store = SqliteUserProfileStore(db)
    store.put(profile)
    assert store.get("usr_one") == profile
    store.put(replace(profile, display_name="José"))
    db.connection.close()
    reopened = SqliteDatabase(path)
    assert SqliteUserProfileStore(reopened).get("usr_one") == replace(profile, display_name="José")
    assert reopened.fetchone("SELECT proposal_id FROM proposals") == ("p",)
