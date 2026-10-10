"""Third-party text (merchant names, ledger descriptions) is data, never instructions (test S01).

Tool payloads carry such text wrapped as {"untrusted_text": "..."} so the model and the UI
can tell it apart. This is the soft layer; the hard layer is that no model output can
authorize anything (permission gate).
"""

from __future__ import annotations

import unicodedata

MAX_LENGTH = 120


def sanitize(text: str) -> str:
    cleaned = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    return cleaned[:MAX_LENGTH]


def wrap_untrusted(text: str) -> dict[str, str]:
    return {"untrusted_text": sanitize(text)}
