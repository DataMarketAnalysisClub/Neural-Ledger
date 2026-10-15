"""The offline PersonalDataDetector: it finds nothing, so the domain rules alone redact statements (the default).

No network, no key, nothing leaves the process. This is the detector of CI, `docker compose up` and the recorded demo.
"""

from __future__ import annotations

from collections.abc import Sequence

from ....domain.privacy.redaction import Span


class NullDetector:
    name = "none"

    def detect(self, texts: Sequence[str]) -> tuple[tuple[Span, ...], ...]:
        return tuple(() for _ in texts)
