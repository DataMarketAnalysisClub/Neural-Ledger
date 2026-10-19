"""G11 (ADR-033): statement and transaction payloads are sealed in SQLite, with the key outside the database."""

from __future__ import annotations

import json
from datetime import date

import pytest

pytest.importorskip("cryptography")

from neural_ledger.adapters.outbound.persistence.field_cipher import PREFIX, FieldCipher, FieldCipherError  # noqa: E402
from neural_ledger.adapters.outbound.persistence.sqlite import SqliteDatabase, SqliteTransactionStore  # noqa: E402
from neural_ledger.bootstrap.container import build  # noqa: E402
from neural_ledger.domain.ledger.categorization import PostedTransaction  # noqa: E402
from neural_ledger.domain.ledger.entities import Transaction, TransactionKind  # noqa: E402
from neural_ledger.domain.shared.serialization import to_primitive  # noqa: E402
from tests.conftest import make_settings  # noqa: E402

KEY = bytes(range(32))


def _posted(user_id: str = "camila", txn_id: str = "t1", merchant: str = "FARMACIA CENTRAL") -> PostedTransaction:
    txn = Transaction(txn_id, "****3456", date(2026, 9, 3), -12_990, merchant, "health", TransactionKind.PURCHASE)
    return PostedTransaction(user_id, "CLP", txn, "stmt_1", 0, "naive_bayes", 0.9)


def test_a_sealed_value_opens_only_with_its_key_and_row():
    cipher = FieldCipher(KEY)
    sealed = cipher.seal('{"merchant": "FARMACIA"}', "transactions|camila|t1")
    assert sealed.startswith(PREFIX) and "FARMACIA" not in sealed
    assert cipher.open(sealed, "transactions|camila|t1") == '{"merchant": "FARMACIA"}'
    with pytest.raises(FieldCipherError):
        cipher.open(sealed, "transactions|diego|t1")  # moved to another user's row
    with pytest.raises(FieldCipherError):
        FieldCipher(bytes(32)).open(sealed, "transactions|camila|t1")  # another key


def test_each_seal_uses_a_fresh_nonce():
    cipher = FieldCipher(KEY)
    assert cipher.seal("same", "a") != cipher.seal("same", "a")


def test_the_store_writes_no_merchant_text_and_reads_it_back(tmp_path):
    path = tmp_path / "ledger.db"
    store = SqliteTransactionStore(SqliteDatabase(path), FieldCipher(KEY))
    store.add([_posted()])
    raw = path.read_bytes() + (path.with_name(path.name + "-wal").read_bytes() if path.with_name(path.name + "-wal").exists() else b"")
    assert b"FARMACIA" not in raw and b"12990" not in raw.replace(b"-", b"")
    assert store.for_user("camila") == (_posted(),)


def test_a_payload_copied_into_another_users_row_does_not_open(tmp_path):
    db = SqliteDatabase(tmp_path / "ledger.db")
    store = SqliteTransactionStore(db, FieldCipher(KEY))
    store.add([_posted("camila", "t1"), _posted("diego", "t2", "OTHER")])
    db.connection.execute("UPDATE transactions SET payload = (SELECT payload FROM transactions WHERE user_id = 'camila') WHERE user_id = 'diego'")
    with pytest.raises(FieldCipherError):
        store.for_user("diego")


def test_a_value_in_clear_in_a_current_database_is_refused(tmp_path):
    """No downgrade: after the migration every payload is sealed, so plain text can only be an edit around the app."""
    db = SqliteDatabase(tmp_path / "old.db")
    legacy = _posted()
    db.connection.execute(
        "INSERT INTO transactions (txn_id, user_id, posted_on, payload) VALUES (?, ?, ?, ?)",
        ("t1", "camila", "2026-09-03", json.dumps(to_primitive(legacy))),
    )
    with pytest.raises(FieldCipherError, match="in clear"):
        SqliteTransactionStore(db, FieldCipher(KEY)).for_user("camila")


def test_values_sealed_with_the_key_itself_still_open_and_new_ones_use_the_derived_key():
    """nlenc1 (G11 before option B) used NL_DATA_KEY as the AES key; nlenc2 uses a subkey derived from it."""
    import base64

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = bytes(12)
    legacy = "nlenc1:" + base64.b64encode(nonce + AESGCM(KEY).encrypt(nonce, b"old", b"transactions|camila|t1")).decode()
    cipher = FieldCipher(KEY)
    assert cipher.open(legacy, "transactions|camila|t1") == "old" and not cipher.is_current(legacy)
    fresh = cipher.seal("new", "transactions|camila|t1")
    assert fresh.startswith(PREFIX) == cipher.is_current(fresh) is True
    raw = base64.b64decode(fresh[len(PREFIX) :])
    with pytest.raises(Exception):  # noqa: B017 - the raw key does not open a value sealed with the derived one
        AESGCM(KEY).decrypt(raw[:12], raw[12:], b"transactions|camila|t1")


def test_the_email_index_is_keyed_and_separate_from_the_field_key():
    cipher, other = FieldCipher(KEY), FieldCipher(bytes(32))
    index = cipher.blind_index("email", "ana@example.com")
    assert index == cipher.blind_index("email", "ana@example.com") and len(index) == 64
    assert index != other.blind_index("email", "ana@example.com")  # another key: another index
    assert "ana" not in index and index != __import__("hashlib").sha256(b"ana@example.com").hexdigest()


def test_offline_runs_create_one_key_file_next_to_the_database_and_reuse_it(tmp_path):
    db_path = tmp_path / "nl.db"
    build(make_settings(persistence="sqlite", sqlite_path=str(db_path)))
    key_file = tmp_path / "nl.db.key"
    first = key_file.read_text(encoding="ascii")
    assert len(bytes.fromhex(first)) == 32
    build(make_settings(persistence="sqlite", sqlite_path=str(db_path)))
    assert key_file.read_text(encoding="ascii") == first


def test_nl_data_key_wins_and_no_key_file_is_written(tmp_path):
    db_path = tmp_path / "nl.db"
    build(make_settings(persistence="sqlite", sqlite_path=str(db_path), data_key=KEY.hex()))
    assert not (tmp_path / "nl.db.key").exists()


def test_live_mode_with_sqlite_refuses_to_start_without_a_data_key(tmp_path):
    settings = make_settings(persistence="sqlite", sqlite_path=str(tmp_path / "nl.db"), llm="openrouter", openrouter_api_key="sk-or-test")
    with pytest.raises(ValueError, match="NL_DATA_KEY"):
        build(settings)


def test_a_malformed_data_key_is_refused():
    with pytest.raises(ValueError, match="NL_DATA_KEY"):
        FieldCipher.from_hex("not-hex")
    with pytest.raises(ValueError, match="32 bytes"):
        FieldCipher.from_hex("ab" * 16)
