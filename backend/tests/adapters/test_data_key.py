"""Key management (option B): the data key comes from a Docker secret or the environment, never from the data volume
in a deployment, and `neural-ledger migrate-data` moves a database off the old on-volume key file."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from neural_ledger.adapters.outbound.persistence.field_cipher import FieldCipher, WrongDataKey  # noqa: E402
from neural_ledger.adapters.outbound.persistence.sqlite import SqliteDatabase  # noqa: E402
from neural_ledger.adapters.outbound.persistence.sqlite_migration import migrate  # noqa: E402
from neural_ledger.bootstrap import data_key  # noqa: E402
from neural_ledger.bootstrap import migrate as migrate_cli  # noqa: E402
from neural_ledger.bootstrap.config import DEV_SECRET, Settings  # noqa: E402
from neural_ledger.bootstrap.container import build  # noqa: E402
from tests.conftest import make_settings  # noqa: E402
from tests.statement_samples import santander_xlsx  # noqa: E402

NEW_KEY = "ab" * 32
OTHER_KEY = "cd" * 32
USER = "usr_key_test"
MERCHANT = "SHOP ONE"

# /proc/self/mountinfo as Docker shows it: the volume at /app/var, the secret as a single-file bind mount.
MOUNTINFO = "\n".join((
    "1 0 0:1 / / rw - overlay overlay rw",
    "2 1 8:1 /var/lib/docker/volumes/ledger-data/_data /app/var rw - ext4 /dev/sda1 rw",
    "3 1 8:1 /opt/neural-ledger/secrets/nl_data_key /run/secrets/nl_data_key ro - ext4 /dev/sda1 rw",
    "4 1 0:5 / /proc rw - proc proc rw",
))


def _settings(tmp_path: Path, **overrides) -> Settings:
    return make_settings(persistence="sqlite", sqlite_path=str(tmp_path / "var" / "nl.db"), **overrides)


def _raw(path: Path) -> bytes:
    wal = path.with_name(path.name + "-wal")
    return path.read_bytes() + (wal.read_bytes() if wal.exists() else b"")


def _offline_database(tmp_path: Path) -> Settings:
    """A database written the old way: no key configured, so the key file sits next to it on the volume."""
    settings = _settings(tmp_path)
    services, _ = build(settings)
    assert services.statements.import_statement(USER, santander_xlsx()).ok
    assert data_key.legacy_key_file(settings.sqlite_path).is_file()
    return settings


# ---- where the key comes from ------------------------------------------------------------------


def test_a_key_file_wins_over_the_environment_and_an_explicit_missing_file_is_an_error(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text(NEW_KEY + "\n", encoding="ascii")
    key = data_key.resolve(make_settings(data_key_file=str(secret), data_key=OTHER_KEY))
    assert key is not None and key.hex == NEW_KEY and key.path == secret and NEW_KEY not in key.source
    env = data_key.resolve(make_settings(data_key=OTHER_KEY))
    assert env is not None and env.hex == OTHER_KEY and env.path is None
    assert data_key.resolve(make_settings()) is None
    with pytest.raises(data_key.DataKeyError, match="not a file"):
        data_key.resolve(make_settings(data_key_file=str(tmp_path / "missing")))


def test_the_docker_secret_is_read_when_it_is_mounted(tmp_path, monkeypatch):
    secret = tmp_path / "run-secrets-nl_data_key"
    secret.write_text(NEW_KEY, encoding="ascii")
    monkeypatch.setattr(data_key, "DOCKER_SECRET", str(secret))
    key = data_key.resolve(make_settings(data_key=OTHER_KEY))
    assert key is not None and key.hex == NEW_KEY and key.source.startswith("secret ")


def test_mount_points_come_from_mountinfo():
    assert data_key.mount_point("/app/var/neural_ledger.db", MOUNTINFO) == "/app/var"
    assert data_key.mount_point("/run/secrets/nl_data_key", MOUNTINFO) == "/run/secrets/nl_data_key"
    assert data_key.mount_point("/app/data/personas", MOUNTINFO) == "/"
    assert data_key.mount_point("/anything", None) is None


@pytest.mark.parametrize(
    "key_path, on_volume",
    [
        ("/run/secrets/nl_data_key", False),  # the Docker secret: a mount of its own
        ("/app/var/neural_ledger.db.key", True),  # the old offline key file
        ("/app/var/keys/nl_data_key", True),  # anywhere else on the same volume
        ("/etc/nl_data_key", False),  # baked into the image's root: not the volume (a bad idea, but not this check)
    ],
)
def test_a_key_file_on_the_databases_mount_is_on_the_data_volume(key_path, on_volume):
    assert data_key.on_data_volume(Path(key_path), "/app/var/neural_ledger.db", MOUNTINFO) is on_volume


def test_without_mountinfo_a_key_file_next_to_the_database_still_counts(tmp_path):
    assert data_key.on_data_volume(tmp_path / "nl.db.key", str(tmp_path / "nl.db"), None)
    assert not data_key.on_data_volume(tmp_path / "keys" / "k", str(tmp_path / "nl.db"), None)


# ---- deployed mode refuses; local mode warns ------------------------------------------------------


def test_deployed_mode_refuses_to_start_without_a_key(tmp_path):
    with pytest.raises(data_key.DataKeyError, match="no data key"):
        build(_settings(tmp_path, deployment="deployed"))
    assert not (tmp_path / "var" / "nl.db.key").exists(), "no key file is created on the volume"
    assert not (tmp_path / "var" / "nl.db").exists(), "and no database either"


def test_deployed_mode_refuses_a_key_file_on_the_data_volume():
    key = data_key.DataKey(NEW_KEY, "file /app/var/neural_ledger.db.key", Path("/app/var/neural_ledger.db.key"))
    settings = make_settings(persistence="sqlite", sqlite_path="/app/var/neural_ledger.db", deployment="deployed")
    with pytest.raises(data_key.DataKeyError, match="same volume"):
        data_key.check(settings, key, mountinfo=MOUNTINFO)
    secret = data_key.DataKey(NEW_KEY, "secret /run/secrets/nl_data_key", Path("/run/secrets/nl_data_key"))
    data_key.check(settings, secret, mountinfo=MOUNTINFO)  # the Docker secret passes


def test_deployed_mode_refuses_to_start_while_the_old_key_file_exists(tmp_path):
    _offline_database(tmp_path)
    with pytest.raises(data_key.DataKeyError, match="migrate-data"):
        build(_settings(tmp_path, deployment="deployed", data_key=NEW_KEY))


def test_deployed_mode_refuses_the_development_hmac_secret(tmp_path):
    with pytest.raises(ValueError, match="NL_HMAC_SECRET"):
        build(_settings(tmp_path, deployment="deployed", data_key=NEW_KEY, hmac_secret=DEV_SECRET))


def test_an_unknown_deployment_is_refused():
    with pytest.raises(ValueError, match="NL_DEPLOYMENT"):
        build(make_settings(deployment="production"))


def test_deployed_mode_starts_with_a_key_from_the_environment(tmp_path):
    services, _ = build(_settings(tmp_path, deployment="deployed", data_key=NEW_KEY))
    assert services.statements.import_statement(USER, santander_xlsx()).ok
    assert not (tmp_path / "var" / "nl.db.key").exists()


def test_a_local_run_without_a_key_warns_loudly_that_it_sits_on_the_volume(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="neural_ledger.bootstrap.data_key"):
        build(_settings(tmp_path))
    assert any("copy of the whole volume reads everything" in r.getMessage() for r in caplog.records)


# ---- the key check -------------------------------------------------------------------------------


def test_a_key_that_does_not_open_the_database_is_refused_before_anything_is_written(tmp_path):
    build(_settings(tmp_path, data_key=NEW_KEY))
    with pytest.raises(WrongDataKey, match="migrate-data"):
        build(_settings(tmp_path, data_key=OTHER_KEY))


def test_a_database_from_before_the_key_check_is_probed_with_its_sealed_values(tmp_path):
    settings = _offline_database(tmp_path)
    SqliteDatabase(settings.sqlite_path).connection.execute("DELETE FROM meta")
    with pytest.raises(WrongDataKey):
        build(_settings(tmp_path, data_key=NEW_KEY))
    build(settings)  # the right key passes and writes the check again
    assert SqliteDatabase(settings.sqlite_path).connection.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 1


# ---- migrate-data ----------------------------------------------------------------------------------


def test_a_dry_run_reports_and_writes_nothing(tmp_path):
    settings = _offline_database(tmp_path)
    old = FieldCipher.from_key_file(data_key.legacy_key_file(settings.sqlite_path))
    db = SqliteDatabase(settings.sqlite_path)
    before = db.connection.execute("SELECT payload FROM transactions ORDER BY rowid").fetchall()
    report = migrate(db, FieldCipher.from_hex(NEW_KEY), [old], dry_run=True)
    assert report.columns["transactions"].rekeyed == len(before) > 0 and report.columns["statements"].rekeyed >= 1
    assert db.connection.execute("SELECT payload FROM transactions ORDER BY rowid").fetchall() == before
    build(settings)  # still opens with the old key


def test_the_migration_rekeys_everything_and_is_idempotent(tmp_path):
    settings = _offline_database(tmp_path)
    legacy = data_key.legacy_key_file(settings.sqlite_path)
    old = FieldCipher.from_key_file(legacy)
    db = SqliteDatabase(settings.sqlite_path)
    first = migrate(db, FieldCipher.from_hex(NEW_KEY), [old])
    assert first.changed > 0
    again = migrate(db, FieldCipher.from_hex(NEW_KEY), [old])
    assert again.changed == 0 and again.columns["transactions"].current == first.columns["transactions"].changed
    legacy.unlink()
    services, _ = build(_settings(tmp_path, deployment="deployed", data_key=NEW_KEY))
    merchants = [t.merchant["untrusted_text"] for t in services.ledger.list_transactions(USER).data.transactions]
    assert any(MERCHANT in m for m in merchants)
    with pytest.raises(WrongDataKey):
        build(_settings(tmp_path, data_key=OTHER_KEY))  # any other key is refused


def test_values_that_open_with_no_given_key_stop_the_migration_and_change_nothing(tmp_path):
    settings = _offline_database(tmp_path)
    db = SqliteDatabase(settings.sqlite_path)
    before = db.connection.execute("SELECT payload FROM statements").fetchall()
    with pytest.raises(WrongDataKey, match="nothing was changed"):
        migrate(db, FieldCipher.from_hex(NEW_KEY), [FieldCipher.from_hex(OTHER_KEY)])
    assert db.connection.execute("SELECT payload FROM statements").fetchall() == before
    assert not db.connection.in_transaction


def test_plain_text_rows_from_before_encryption_are_sealed(tmp_path):
    settings = _offline_database(tmp_path)
    db = SqliteDatabase(settings.sqlite_path)
    old = FieldCipher.from_key_file(data_key.legacy_key_file(settings.sqlite_path))
    rowid, user_id, txn_id, sealed = db.connection.execute("SELECT rowid, user_id, txn_id, payload FROM transactions LIMIT 1").fetchone()
    db.connection.execute("UPDATE transactions SET payload = ? WHERE rowid = ?", (old.open(sealed, f"transactions|{user_id}|{txn_id}"), rowid))
    report = migrate(db, FieldCipher.from_hex(NEW_KEY), [old])
    assert report.columns["transactions"].sealed == 1
    db.connection.close()
    assert MERCHANT.encode() not in _raw(Path(settings.sqlite_path))


def test_the_command_migrates_and_tells_the_operator_to_delete_the_old_key(tmp_path):
    settings = _offline_database(tmp_path)
    secret = tmp_path / "secrets" / "nl_data_key"
    secret.parent.mkdir()
    secret.write_text(NEW_KEY, encoding="ascii")
    target = _settings(tmp_path, data_key_file=str(secret))
    lines: list[str] = []
    assert migrate_cli.main(["--dry-run"], target, lines.append) == 0
    assert any("would change" in line for line in lines) and not any("DELETE" in line for line in lines)
    lines.clear()
    assert migrate_cli.main([], target, lines.append) == 0
    assert any("DELETE THE OLD KEY FILE NOW" in line and str(data_key.legacy_key_file(settings.sqlite_path)) in line for line in lines)
    assert all(NEW_KEY not in line for line in lines), "the key is never printed"
    lines.clear()
    assert migrate_cli.main([], target, lines.append) == 0
    assert any("changed 0 value(s)" in line for line in lines)


def test_the_command_refuses_the_old_key_file_as_the_new_key(tmp_path):
    settings = _offline_database(tmp_path)
    legacy = data_key.legacy_key_file(settings.sqlite_path)
    lines: list[str] = []
    assert migrate_cli.main([], _settings(tmp_path, data_key_file=str(legacy)), lines.append) == 2
    assert "old key file" in lines[-1]


def test_the_command_needs_a_new_key_and_a_database(tmp_path):
    lines: list[str] = []
    assert migrate_cli.main([], _settings(tmp_path, data_key=NEW_KEY), lines.append) == 2 and "no database" in lines[-1]
    _offline_database(tmp_path)
    assert migrate_cli.main([], _settings(tmp_path), lines.append) == 2 and "no new key" in lines[-1]


def test_the_cli_dispatches_migrate_data_before_building_the_app(tmp_path, monkeypatch):
    from neural_ledger.bootstrap import cli

    settings = _offline_database(tmp_path)
    monkeypatch.setenv("NL_PERSISTENCE", "sqlite")
    monkeypatch.setenv("NL_SQLITE_PATH", settings.sqlite_path)
    monkeypatch.setenv("NL_DATA_KEY", NEW_KEY)
    monkeypatch.setenv("NL_DEPLOYMENT", "deployed")  # building the app would refuse: the old key file is still there
    assert cli.main(["migrate-data", "--dry-run"]) == 0


def test_the_database_file_is_a_plain_sqlite_file_after_migration(tmp_path):
    settings = _offline_database(tmp_path)
    db = SqliteDatabase(settings.sqlite_path)
    migrate(db, FieldCipher.from_hex(NEW_KEY), [FieldCipher.from_key_file(data_key.legacy_key_file(settings.sqlite_path))])
    db.connection.close()
    assert sqlite3.connect(settings.sqlite_path).execute("PRAGMA integrity_check").fetchone() == ("ok",)
