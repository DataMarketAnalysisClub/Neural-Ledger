"""Deterministic response verifier (Financial Core section 7, tests S07 and S08).

An explanation passes only if:
  * every money figure in it matches a fact (exactly, or to the nearest 1,000 when the text
    says "about"), and every percentage matches a percentage fact;
  * every warning (caveat) is mentioned;
  * it does not use banned wording ("safe money", guarantees);
  * it does not claim the opposite of a non-fitting verdict;
  * it does not claim an execution that did not succeed.
A failed explanation is replaced by a deterministic one built from the facts.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from ..shared.envelope import Caveat, Fact
from .amounts import Number, extract_numbers

_BANNED = re.compile(
    r"\bsafe money\b|\bsafe(?:ly)? to (?:spend|buy)\b|\bdinero seguro\b|\bguarantee(?:d|s)?\b|\bgarantizad[oa]s?\b",
    re.IGNORECASE,
)
_AFFIRMS_PURCHASE = re.compile(
    r"\byou can (?:definitely )?afford it\b|\bgo ahead and buy\b|\bno problem\b|\bpuedes comprarlo\b|\bsin problema\b",
    re.IGNORECASE,
)
_CLAIMS_EXECUTION = re.compile(
    r"\b(?:i(?:'ve| have) (?:created|set up|executed|activated)|(?:rule|transfer) (?:is|has been) (?:created|active|executed|set up)"
    r"|he (?:creado|ejecutado|activado)|(?:regla|transferencia) (?:fue|está|quedó) (?:creada|activa|ejecutada)"
    # Money the agent says it moved itself: with investment figures among the facts, "I invested 900,000" could
    # otherwise quote a real number in a false claim (S30). Not "sent": "I've sent you a proposal" is honest.
    r"|i(?:'ve| have)? (?:moved|transferred|invested|deposited)"
    r"|he (?:movido|transferido|invertido|depositado)|transfer[ií]|mov[ií]|invert[ií]|deposit[eé])\b",
    re.IGNORECASE,
)
_NOT_FITTING = {"FITS_TYPICAL_ONLY", "BREACHES_ALL", "BASELINE_BREACH"}

# Honest mistakes a model may correct once. Banned wording, contradictions and false execution claims are never
# retried: they go straight to the deterministic narration.
REPAIRABLE_KINDS = frozenset({"UNSUPPORTED_NUMBER", "MISSING_WARNING"})


@dataclass(frozen=True, slots=True)
class VerificationIssue:
    kind: str  # UNSUPPORTED_NUMBER | MISSING_WARNING | BANNED_WORDING | CONTRADICTION | FALSE_EXECUTION_CLAIM
    detail: str


@dataclass(frozen=True, slots=True)
class VerificationResult:
    ok: bool
    issues: tuple[VerificationIssue, ...]
    numbers_checked: int


def _matches(number: Number, facts: Sequence[Fact], money_units: frozenset[str]) -> bool:
    for fact in facts:
        if isinstance(fact.value, str) or isinstance(fact.value, bool):
            continue
        target = abs(Decimal(str(fact.value)))
        if number.is_percent:
            if fact.unit != "%":
                continue
            tolerance = Decimal("0.5") if number.approximate else Decimal("0.05")
            if abs(target - number.value) <= tolerance:
                return True
            continue
        if fact.unit not in money_units:
            continue
        if target == number.value:
            return True
        if number.approximate and abs(target - number.value) <= 500:
            return True
    return False


def verify_explanation(
    text: str,
    facts: Sequence[Fact],
    caveats: Sequence[Caveat],
    *,
    money_units: frozenset[str] = frozenset({"CLP"}),
    executions_succeeded: int = 0,
) -> VerificationResult:
    issues: list[VerificationIssue] = []
    numbers = extract_numbers(text)
    for n in numbers:
        if not _matches(n, facts, money_units):
            issues.append(VerificationIssue("UNSUPPORTED_NUMBER", n.text))
    lowered = text.lower()
    for caveat in caveats:
        if caveat.must_mention and not any(token.lower() in lowered for token in caveat.must_mention):
            issues.append(VerificationIssue("MISSING_WARNING", caveat.code))
    banned = _BANNED.search(text)
    if banned:
        issues.append(VerificationIssue("BANNED_WORDING", banned.group(0)))
    verdicts = {str(f.value) for f in facts if f.key == "purchase.verdict"}
    if verdicts & _NOT_FITTING:
        claim = _AFFIRMS_PURCHASE.search(text)
        if claim:
            issues.append(VerificationIssue("CONTRADICTION", claim.group(0)))
    if executions_succeeded == 0:
        claim = _CLAIMS_EXECUTION.search(text)
        if claim:
            issues.append(VerificationIssue("FALSE_EXECUTION_CLAIM", claim.group(0)))
    return VerificationResult(not issues, tuple(issues), len(numbers))
