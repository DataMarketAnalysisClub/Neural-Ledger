from __future__ import annotations

from collections.abc import Sequence

from ....application.ports import ReadOnlyProfile, UserProfileStore
from ....domain.user.profile import UserProfile


class PersonaOverlayProfileStore:
    def __init__(self, personas: Sequence[UserProfile], inner: UserProfileStore) -> None:
        self._personas = {profile.user_id: profile for profile in personas}
        self._inner = inner

    def get(self, user_id: str) -> UserProfile | None:
        return self._personas.get(user_id) or self._inner.get(user_id)

    def put(self, profile: UserProfile) -> None:
        if profile.user_id in self._personas:
            raise ReadOnlyProfile(profile.user_id)
        self._inner.put(profile)
