"""Where the SQLite data key comes from (G11), and the checks that keep it off the data volume.

Order: a key file (NL_DATA_KEY_FILE, or the Docker secret /run/secrets/nl_data_key when it exists), then the
NL_DATA_KEY environment variable. A Docker secret is mounted into the container on its own, so a copy of the
data volume (or of a backup of it) holds ciphertext without the key that opens it.

NL_DEPLOYMENT=deployed (a server reachable by others) refuses to start without a key, with a key file on the
same mount as the database, or while the old offline key file `<db>.key` is still next to the database. Local
runs keep the convenient fallback: a random key in `<db>.key`, with a loud warning that it sits on the data
volume. `neural-ledger migrate-data` moves a database from that file to a real key.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

logger = logging.getLogger(__name__)

DOCKER_SECRET = "/run/secrets/nl_data_key"
DEPLOYMENTS = ("local", "deployed")
MOUNTINFO = "/proc/self/mountinfo"


class DataKeyError(ValueError):
    """The key is missing, unreadable or stored where it protects nothing; the app does not start."""


@dataclass(frozen=True)
class DataKey:
    hex: str
    source: str  # "secret <path>", "file <path>" or "env NL_DATA_KEY"; never the key itself
    path: Path | None = None  # the file it was read from, if any


def legacy_key_file(sqlite_path: str) -> Path:
    """The key file offline runs create next to the database (before this change, also in Docker)."""
    return Path(f"{sqlite_path}.key")


def resolve(settings: Settings) -> DataKey | None:
    """The configured key, or None. An explicit NL_DATA_KEY_FILE that does not exist is an error, not a fallback."""
    explicit = settings.data_key_file
    path = Path(explicit or DOCKER_SECRET)
    if path.is_file():
        try:
            value = path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise DataKeyError(f"cannot read the data key file {path} ({exc.__class__.__name__})") from None
        return DataKey(value, f"{'file' if explicit else 'secret'} {path}", path)
    if explicit:
        raise DataKeyError(f"NL_DATA_KEY_FILE points to {path}, which is not a file")
    if settings.data_key:
        return DataKey(settings.data_key, "env NL_DATA_KEY")
    return None


def _unescape(field: str) -> str:
    return field.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


def mount_point(path: str | Path, mountinfo: str | None) -> str | None:
    """The mount point holding path (longest matching mount in /proc/self/mountinfo), or None without mountinfo."""
    if mountinfo is None:
        return None
    real = os.path.realpath(path)
    best: str | None = None
    for line in mountinfo.splitlines():
        fields = line.split(" ")
        if len(fields) < 5:
            continue
        point = _unescape(fields[4])
        inside = real == point or real.startswith(point.rstrip("/") + "/")
        if inside and (best is None or len(point) > len(best)):
            best = point
    return best


def _read_mountinfo() -> str | None:
    try:
        return Path(MOUNTINFO).read_text(encoding="utf-8")
    except OSError:
        return None  # not Linux: fall back to the directory check


def on_data_volume(key_path: Path, sqlite_path: str, mountinfo: str | None) -> bool:
    """True when the key file shares the database's mount (a Docker volume) or sits in its directory."""
    database = Path(sqlite_path)
    if Path(os.path.realpath(key_path)).parent == Path(os.path.realpath(database)).parent:
        return True
    key_mount, db_mount = mount_point(key_path, mountinfo), mount_point(database, mountinfo)
    return key_mount is not None and key_mount == db_mount and key_mount != "/"


def check(settings: Settings, key: DataKey | None, *, mountinfo: str | None = None, read_mountinfo: bool = True) -> None:
    """Refuse what deployed mode must not run with; warn about the same things locally."""
    if settings.deployment not in DEPLOYMENTS:
        raise DataKeyError(f"unknown NL_DEPLOYMENT {settings.deployment!r} (local | deployed)")
    if settings.persistence != "sqlite" or settings.sqlite_path == ":memory:":
        return
    deployed = settings.deployment == "deployed"
    if mountinfo is None and read_mountinfo:
        mountinfo = _read_mountinfo()
    legacy = legacy_key_file(settings.sqlite_path)
    problems: list[str] = []
    if key is None:
        problems.append(
            "no data key: set a Docker secret at /run/secrets/nl_data_key (docker-compose.data-key.yml), "
            "NL_DATA_KEY_FILE, or NL_DATA_KEY (64 hex characters)"
        )
    elif key.path is not None and on_data_volume(key.path, settings.sqlite_path, mountinfo):
        problems.append(f"the data key file {key.path} is on the same volume as the database; mount it as a secret instead")
    if key is not None and legacy.exists() and (key.path is None or os.path.realpath(key.path) != os.path.realpath(legacy)):
        problems.append(
            f"the old key file {legacy} is still on the data volume: run `neural-ledger migrate-data`, then delete it"
        )
    if not problems:
        return
    if deployed:
        raise DataKeyError("NL_DEPLOYMENT=deployed refuses to start: " + "; ".join(problems))
    if key is not None:  # a local run with a real key: the problems are worth a warning, not a refusal
        for problem in problems:
            logger.warning("data key: %s", problem)


def warn_key_file_fallback(path: Path) -> None:
    """Local runs only: the random key file next to the database protects a stray copy of the .db, not the volume."""
    logger.warning(
        "\n%s\nWARNING: the SQLite data key is the file %s, next to the database.\n"
        "A copy of the database alone reads nothing, but a copy of the whole volume reads everything.\n"
        "Fine for local development; never for a server. Deployments set NL_DEPLOYMENT=deployed and mount\n"
        "the key as a Docker secret (docker-compose.data-key.yml, docs/SECURITY.md, 'Key management').\n%s",
        "!" * 100, path, "!" * 100,
    )
