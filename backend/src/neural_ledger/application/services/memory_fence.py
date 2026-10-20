"""The memory fence (ADR-048 §6): one lock per user that orders memory changes against what is published from memory.

Every change of a user's memory counters (consent, confirmation, chain deletion, account erasure) runs inside the
fence, and so does each memory linearization point of a chat turn: the authorization check before a request goes to
a model, and the final check together with the history write that publishes a reply. So a check and the write it
guards see a change either whole or not at all. The fence is held only for local reads and writes, never through a
model or network call: a revocation while a model answers never waits for it.

It is per user (other users never wait) and in process: it orders what one API process does, which is how the API
runs (conversations live in that process too). A memory change from another process is still caught by the counters,
which the history filter compares on every read, but not ordered against this process's publication.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class MemoryFence:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, tuple[threading.Lock, int]] = {}  # per user: the lock and how many hold or wait for it

    @contextmanager
    def held(self, user_id: str) -> Iterator[None]:
        """Hold the user's fence. Never nest it, and never take it inside a store's lock: it is always the outermost."""
        with self._guard:
            lock, users = self._locks.get(user_id, (threading.Lock(), 0))
            self._locks[user_id] = (lock, users + 1)
        try:
            with lock:
                yield
        finally:
            with self._guard:
                lock, users = self._locks[user_id]
                if users == 1:
                    del self._locks[user_id]  # nobody else holds or waits: the map does not grow with every user
                else:
                    self._locks[user_id] = (lock, users - 1)
