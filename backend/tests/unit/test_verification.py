from __future__ import annotations

from neural_ledger.domain.agent.verification import extract_numbers, verify_explanation
from neural_ledger.domain.shared.envelope import Caveat, Fact

FACTS = (
    Fact("protected_surplus", 20_000, "CLP", "x"),
    Fact("purchase.installment", 38_995, "CLP", "x"),
    Fact("purchase.effective_annual_rate_pct", 34.5, "%", "x"),
    Fact("alternative_2.amount", 205_000, "CLP", "x"),
    Fact("purchase.verdict", "FITS_TYPICAL_ONLY", "verdict", "x"),
)
RATE = (Caveat("RATE_ASSUMED", "Monthly rate assumed at 2.5%", ("2.5%", "assum")),)


def test_numbers_are_parsed_in_common_formats():
    values = [int(n.value) for n in extract_numbers("CLP 400k, 1.8M, 38.995 and 1,800,000; 12 cuotas in 2026-12, year 2027")]
    assert values == [400_000, 1_800_000, 38_995, 1_800_000]


def test_matching_facts_pass():
    text = "Each cuota is 38,995 CLP (34.5% effective annual); about 205,000 CLP would fit. Rate assumed at 2.5%."
    result = verify_explanation(text, FACTS + (Fact("rate", 2.5, "%", "x"),), RATE)
    assert result.ok, result.issues


def test_invented_number_fails():
    result = verify_explanation("You can spend 300,000 CLP.", FACTS, ())
    assert [i.kind for i in result.issues] == ["UNSUPPORTED_NUMBER"]


def test_missing_warning_fails():
    result = verify_explanation("Each cuota is 38,995 CLP.", FACTS, RATE)
    assert [i.kind for i in result.issues] == ["MISSING_WARNING"]


def test_banned_wording_and_contradiction_fail():
    kinds = {i.kind for i in verify_explanation("Go ahead and buy it, that's safe money.", FACTS, ()).issues}
    assert kinds == {"BANNED_WORDING", "CONTRADICTION"}


def test_false_execution_claim_fails_only_without_success():
    text = "I've created the savings rule."
    assert not verify_explanation(text, FACTS, ()).ok
    assert verify_explanation(text, FACTS, (), executions_succeeded=1).ok


def test_claims_of_moving_money_fail_and_honest_sentences_about_money_pass():
    claims = (
        "I moved 20,000 CLP for you.", "I've transferred 20,000 CLP.", "I invested 20,000 CLP in your goal.", "I have deposited 20,000 CLP.",
        "He transferido 20,000 CLP.", "Listo, invertí 20,000 CLP.", "Moví 20,000 CLP a tu meta.", "Deposité 20,000 CLP.",
    )
    for text in claims:
        assert [i.kind for i in verify_explanation(text, FACTS, ()).issues] == ["FALSE_EXECUTION_CLAIM"], text
    honest = (
        "You deposited a net 20,000 CLP, so that is a gain so far.",
        "I've sent you a proposal for 20,000 CLP to confirm in the app.",
        "Nothing moves until you confirm.",
        "Has invertido 20,000 CLP en tu meta.",
        "Your investments moved up this month.",
    )
    for text in honest:
        assert verify_explanation(text, FACTS, ()).ok, text
