"""Deterministic narrator: turns tool payloads into plain-language text using only their numbers.

Used by the scripted (offline) language model and as the safe fallback whenever a real
model's explanation fails verification. Every figure printed here comes from a fact, so its
output always passes the verifier (tests/application/test_narration.py checks this).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from ...domain.agent.verification import verify_explanation
from ...domain.shared.envelope import Fact

Payload = Mapping[str, Any]

REFUSAL_INJECTION = (
    "I can't follow that instruction. I only analyze your finances and carry out actions you "
    "confirm in the app, within fixed limits. This request was logged."
)
REFUSAL_SCOPE = (
    "I can't help with investments, crypto or tax advice. I can check whether a purchase fits your "
    "future commitments, show what is really available, and set up a savings rule."
)
CLARIFY = "Just to be sure: do you want to check a purchase, see your forecast, or set up a savings rule?"
READ_ONLY_NOTE = "I'm in read-only mode right now, so I can analyze but not prepare or execute actions."
GREETING = (
    "Hi! I can check whether a purchase fits your future commitments, show your cash-flow forecast, "
    "and help you set up a savings rule."
)
# Explanations come from the concept cards (ADR-039): the top passage, then this sentence in the card's language.
NOT_ADVICE_SENTENCE = {
    "es": "Esto es información general, no es una recomendación para tu situación.",
    "en": "This is general information, not a recommendation for your situation.",
}
_NO_CARD = {
    "es": (
        "No tengo una ficha que explique ese término, así que no lo voy a explicar de memoria. Sí puedo revisar si "
        "una compra calza con tus compromisos futuros, mostrarte tu proyección y lo que realmente tienes disponible, "
        "o preparar una regla de ahorro."
    ),
    "en": (
        "I don't have a card that explains that term, so I won't explain it from memory. I can check whether a "
        "purchase fits your future commitments, show your forecast and what is really available, or set up a savings rule."
    ),
}
_NO_CARDS_NOW = {
    "es": "Mis fichas de conceptos no están disponibles en este momento, así que no lo voy a explicar de memoria.",
    "en": "My concept cards are not available right now, so I won't explain it from memory.",
}
MAX_PASSAGE_SENTENCES = 2


def no_concept_card(lang: str = "en", unavailable: bool = False) -> str:
    """What the copilot says when no concept card explains the question: never a definition from memory."""
    table = _NO_CARDS_NOW if unavailable else _NO_CARD
    return table.get(lang, table["en"])
NO_RESULT = "I couldn't get a result for that. Could you rephrase?"

_BLOCK_SENTENCES = {
    "AUTHORIZATION_EXPIRED": "The authorization expired, so please confirm again in the app.",
    "AUTHORIZATION_REPLAYED": "That authorization was already used.",
    "AUTHORIZATION_TAMPERED": "The stored terms no longer match what you confirmed.",
    "AUTHORIZATION_NOT_FOUND": "There is no confirmed authorization for that.",
    "WRONG_OWNER": "That authorization belongs to someone else.",
    "UNKNOWN_DESTINATION": "That destination is not allowed.",
    "UNKNOWN_SOURCE": "That source account is not allowed.",
    "NEW_BENEFICIARY": "Adding a new beneficiary is not allowed.",
    "LIMIT_CHANGE": "Changing limits is not allowed.",
    "CREDENTIAL_CHANGE": "Changing credentials is not allowed.",
    "POLICY_OVERRIDE": "I can't override the policy.",
    "SELF_ESCALATION": "I can't give myself more permissions or confirm on your behalf.",
    "AMOUNT_OVER_LIMIT": "That amount is over the per-action limit.",
    "TIER_NOT_ALLOWED": "That action is not available in this conversation state.",
    "UNKNOWN_TOOL": "That capability does not exist.",
    "PROPOSAL_NOT_FOUND": "I couldn't find that proposal.",
    "PROPOSAL_EXPIRED": "That proposal expired; ask me to prepare it again.",
    "PROPOSAL_NOT_PENDING": "That proposal was already handled.",
    "TERMS_CHANGED": "The terms shown don't match the proposal.",
    "AUDIT_UNAVAILABLE": "The audit log is unavailable, so nothing can be executed.",
}

_FACTOR_PHRASES = {
    "conservative_headroom": "your tightest month leaves very little above your minimum balance",
    "reserve_coverage": "your reserve covers less than the target months of essentials",
    "income_stability": "your income varies a lot from month to month",
    "debt_service": "debt payments take a large share of your income",
    "stress_coverage": "an unexpected expense would leave your reserve thin",
}


def _money(value: int, currency: str) -> str:
    return f"{abs(int(value)):,} {currency}"


def _bucket_name(bucket: str) -> str:
    return f"your {bucket.split(':', 1)[1]} goal" if bucket.startswith("goal:") else "your reserve"


def _caveat_sentences(payload: Payload) -> list[str]:
    return [w["message"] for w in payload.get("warnings", ()) if w.get("message")]


def narrate(results: Sequence[tuple[str, Payload]], currency: str) -> str:
    """One sentence per distinct statement: a tool called twice with the same input, or the same warning raised
    by several tools, is said once. The warnings keep their tokens, so the verifier still sees each one."""
    sentences: list[str] = []
    narrated: list[tuple[str, Payload]] = []
    told_document = any(name == "get_latest_document" for name, _ in results)
    for name, payload in results:
        if told_document and name == "get_spending_status" and isinstance(payload.get("data"), dict):
            payload = {**payload, "data": {**payload["data"], "latest_receipt": None}}  # the document was just described
        if (name, payload) in narrated:
            continue
        narrated.append((name, payload))
        sentences += [s for s in _narrate_one(name, payload, currency) if s not in sentences]
    return " ".join(sentences) if sentences else NO_RESULT


def _narrate_one(name: str, payload: Payload, cur: str) -> list[str]:
    status = payload.get("status")
    if status == "BLOCKED" and "outcome" not in payload:
        reason = payload.get("reason", "")
        return [_BLOCK_SENTENCES.get(reason, "I can't do that.") + " The attempt was logged."]
    if status == "INVALID_INPUT":
        return [f"I couldn't use that input ({payload.get('field')}): {payload.get('message')}"]
    if status == "INSUFFICIENT_DATA" and name == "search_financial_concepts":
        return [no_concept_card("en", unavailable="knowledge_base" in payload.get("missing", ()))]
    if status == "INSUFFICIENT_DATA":
        missing =", ".join(payload.get("missing", ())) or "some data"
        return [f"I don't have enough data to answer that yet (missing: {missing}), so I won't guess."]
    handler = _HANDLERS.get(name)
    if handler is None:
        return []
    if name in _SAYS_ITS_OWN_CAVEATS:
        return handler(payload, cur)
    return handler(payload, cur) + _caveat_sentences(payload)


def _financial_state(p: Payload, cur: str) -> list[str]:
    d = p["data"]
    return [f"Your checking balance is {_money(d['checking'], cur)} and your reserve holds {_money(d['reserve'], cur)}."]


def _commitments(p: Payload, cur: str) -> list[str]:
    schedule = p["data"]["schedule"]
    if not schedule:
        return ["You have no commitments in this period."]
    peak = max(schedule, key=lambda s: (s["total"], s["month"]))
    return [f"Your committed payments peak in {peak['month']} at {_money(peak['total'], cur)}."]


def _forecast(p: Payload, cur: str) -> list[str]:
    d = p["data"]
    lowest = min(d["cycles"], key=lambda c: (c["headroom"], c["month"]))
    side = "above" if lowest["headroom"] >= 0 else "below"
    text = [
        f"In the {d['scenario']} scenario, your lowest balance before payday is {_money(lowest['trough'], cur)} "
        f"in {lowest['month']}, {_money(lowest['headroom'], cur)} {side} your {_money(d['floor'], cur)} minimum."
    ]
    breaches = [c["month"] for c in d["cycles"] if c["headroom"] < 0]
    if breaches:
        text.append(f"It falls below the minimum in {', '.join(breaches)}.")
    return text


def _purchase(p: Payload, cur: str) -> list[str]:
    d = p["data"]
    q = d["quote"]
    eff = _fact(p, "purchase.effective_annual_rate_pct")
    impacts = {i["scenario"]: i for i in d["impacts"]}
    floor = _money(_fact(p, "liquidity_floor"), cur)
    text = [
        f"{_money(q['principal'], cur)} in {q['installments']} cuotas costs {_money(q['installment'], cur)} a month: "
        f"{_money(q['total_cost'], cur)} in total, {_money(q['total_interest'], cur)} of interest ({eff}% effective annual)."
    ]
    verdict = d["verdict"]
    cons, typ = impacts["conservative"], impacts["typical"]
    if verdict == "FITS_ALL":
        text.append(
            f"It fits both your typical and conservative forecasts: your tightest month stays "
            f"{_money(cons['lowest_headroom_after'], cur)} above your {floor} minimum."
        )
    elif verdict == "FITS_TYPICAL_ONLY":
        text.append(
            f"It fits a typical month, but in the conservative scenario your balance before payday in "
            f"{cons['binding_month_after']} would drop to {_money(cons['trough_after_in_binding_month'], cur)}, "
            f"{_money(cons['lowest_headroom_after'], cur)} below your {floor} minimum."
        )
    elif verdict == "BREACHES_ALL":
        text.append(
            f"It doesn't fit: even in a typical month your balance before payday in {typ['binding_month_after']} "
            f"would drop to {_money(typ['trough_after_in_binding_month'], cur)}, below your {floor} minimum."
        )
    else:
        text.append(
            f"Before any purchase, your conservative forecast already goes {_money(cons['lowest_headroom_before'], cur)} "
            f"below your {floor} minimum, so I can't recommend new cuotas until your income buffer allows it."
        )
    options = []
    for alt in d.get("alternatives", ()):
        if alt["kind"] == "defer_start":
            options.append(f"start the cuotas in {alt['first_installment_month']} ({_money(alt['installment'], cur)} a month)")
        elif alt["kind"] == "change_installments":
            options.append(f"use {alt['installments']} cuotas instead ({_money(alt['installment'], cur)} a month)")
        elif alt["kind"] == "reduce_amount":
            options.append(f"keep {alt['installments']} cuotas with a smaller amount of about {_money(alt['amount'], cur)}")
    if options:
        text.append("Options that fit: " + "; or ".join(options) + ". I won't suggest using your reserve.")
    return text


def _surplus(p: Payload, cur: str) -> list[str]:
    d = p["data"]
    ps = d["protected_surplus"]
    if ps < 0:
        return [
            f"Your conservative forecast already falls {_money(ps, cur)} below your minimum in {d['binding_month']}, "
            "so there is no protected surplus right now."
        ]
    text = [
        f"Your protected surplus is {_money(ps, cur)}, set by {d['binding_month']}: that is how much could leave "
        "checking today without any conservative month dropping below your minimum."
    ]
    if d.get("plan_amount"):
        text.append(f"This already includes a savings rule of {_money(d['plan_amount'], cur)} a month.")
    later = [f for f in d["monthly_free_flow"] if f["month"] > d["binding_month"] and f["amount"] > 0]
    if later:
        text.append(f"From {later[0]['month']}, about {_money(later[0]['amount'], cur)} a month stays free.")
    return text


def _capacity(p: Payload, cur: str) -> list[str]:
    d = p["data"]
    reasons = [_FACTOR_PHRASES.get(name, name) for name in d["binding_factors"]]
    return [f"Your financial capacity is {d['level']} because " + " and ".join(reasons) + "."]


def _tolerance(p: Payload, cur: str) -> list[str]:
    return [f"Your stated risk tolerance is {p['data']['tolerance']}."]


def _permitted(p: Payload, cur: str) -> list[str]:
    d = p["data"]
    return [
        f"Your permitted profile is {d['permitted']}: the lower of your tolerance ({d['tolerance']}) "
        f"and your financial capacity ({d['capacity']})."
    ]


def _plan(p: Payload, cur: str) -> list[str]:
    d = p["data"]
    if not d["amount"]:
        return [
            "I can't propose a recurring savings rule right now: your conservative available flow is not "
            "positive in the coming months."
        ]
    share = round(d["share"] * 100)
    text = [
        f"I can propose a savings rule of {_money(d['amount'], cur)} a month starting {d['start_month']}: "
        f"{share}% of your lowest available monthly flow ({_money(d['lowest_available_in_window'], cur)}), "
        "rounded down so no conservative month falls below your minimum."
    ]
    for g in d.get("goal_status", ()):
        if g["funded_monthly"]:
            text.append(f"It funds your {g['name'].lower()} goal, complete by {g['projected_completion']}.")
    for r in d.get("requirements", ()):
        if r["bucket"] == "reserve" and r["required_monthly"] and r["funded_monthly"] == 0 and r["funded_from"]:
            text.append(
                f"The reserve top-up ({_money(r['required_monthly'], cur)} a month) starts in {r['funded_from']}."
            )
    return text


def _action(p: Payload, cur: str) -> list[str]:
    outcome = p.get("outcome", {})
    status = outcome.get("status")
    terms = (outcome.get("proposal") or outcome.get("authorization") or {}).get("terms") or {}
    floor = terms.get("action") == "set_liquidity_floor"
    if status == "PROPOSED" and floor:
        return [
            f"Please review and confirm in the app: a liquidity floor rule of {_money(terms['amount'], cur)}, the minimum "
            f"balance your checking account keeps every month, starting {terms['effective_date']}. "
            "Once it is active, forecasts, plans and purchase checks use it instead of the default floor. Nothing changes until you confirm."
        ]
    if status == "EXECUTED" and floor:
        return [f"Done: your liquidity floor of {_money(terms['amount'], cur)} is now active."]
    if status == "PROPOSED":
        return [
            f"Please review and confirm in the app: a {terms['frequency']} transfer of {_money(terms['amount'], cur)} "
            f"from {terms['source_account']} to {terms['destination'].replace('_', ' ')}, starting {terms['effective_date']}. "
            "Nothing moves until you confirm."
        ]
    if status == "EXECUTED":
        return [f"Done: the savings rule of {_money(terms['amount'], cur)} a month is now active in the sandbox."]
    if status == "FAILED":
        return ["The sandbox could not complete the action, so nothing was executed. Please confirm again to retry."]
    if status == "BLOCKED":
        reason = outcome.get("reason", "")
        if reason == "AUTHORIZATION_MISMATCH":
            first = (
                f"You authorized {_money(outcome['authorized_amount'], cur)}, but the request was for "
                f"{_money(outcome['requested_amount'], cur)}."
            )
        else:
            first = _BLOCK_SENTENCES.get(reason, "That action is not allowed.")
        return ["I can't execute that. " + first + " Nothing was changed, and the attempt was logged."]
    return []


def _pending(p: Payload, cur: str) -> list[str]:
    d = p["data"]
    return [f"You have {len(d['proposals'])} pending proposals and {len(d['authorizations'])} unused authorizations."]


def _audit(p: Payload, cur: str) -> list[str]:
    return [f"There are {len(p['data']['events'])} audit events in this session."]


def _profile(p: Payload, cur: str) -> list[str]:
    return [f"Profile loaded for {p['data']['display_name']['untrusted_text']}."]


def _spending(p: Payload, cur: str) -> list[str]:
    d = p["data"]
    c = d["check"]
    text = []
    receipt = d.get("latest_receipt")
    # A receipt is worth a sentence while it bears on this cycle; the workflow card already said why an old one does not.
    if receipt and receipt.get("total") is not None and (receipt.get("counted") or receipt.get("matched_transaction") or not receipt["verified"]):
        amount, category = _money(receipt["total"], cur), receipt["category"]
        if not receipt["verified"]:
            text.append(f"Your latest receipt ({amount}) could not be verified, so it is not counted.")
        elif receipt.get("matched_transaction"):
            text.append(f"Your latest receipt of {amount} ({category}) is already on your bank statement, so it is counted once.")
        else:
            text.append(f"Your latest receipt of {amount} ({category}, {receipt['issued_on']}) is counted.")
    if c["overspend"] == 0:
        text.append(
            f"This cycle you have logged {_money(c['logged'], cur)} of the {_money(c['assumed'], cur)} your conservative "
            f"forecast counts on, so {_money(c['left'], cur)} is left: about {_money(c['per_day'], cur)} a day for the "
            f"next {c['days_left']} days, until {c['window_end']}."
        )
        if c["protected_surplus"] >= 0:
            text.append(f"Your protected surplus of {_money(c['protected_surplus'], cur)} stays untouched.")
        else:
            text.append(
                f"Careful: even without this spending, your conservative forecast already falls "
                f"{_money(c['protected_surplus'], cur)} below your minimum, so there is no protected surplus right now."
            )
    elif not c["projected"]:
        text.append(
            f"This cycle you have logged {_money(c['logged'], cur)}, {_money(c['overspend'], cur)} more than the "
            f"{_money(c['assumed'], cur)} your conservative forecast counts on for a pay cycle."
        )
    elif c["surplus_after"] >= 0:
        text.append(
            f"This cycle you have logged {_money(c['logged'], cur)}, {_money(c['overspend'], cur)} more than the "
            f"{_money(c['assumed'], cur)} your conservative forecast counts on, so your protected surplus is down to "
            f"{_money(c['surplus_after'], cur)}."
        )
    else:
        text.append(
            f"This cycle you have logged {_money(c['logged'], cur)}, {_money(c['overspend'], cur)} more than the "
            f"{_money(c['assumed'], cur)} your conservative forecast counts on, which is more than your protected surplus "
            f"of {_money(c['protected_surplus'], cur)}."
        )
    return text


def _document(p: Payload, cur: str) -> list[str]:
    d = p["data"]
    if d["kind"] == "receipt":
        r = d["receipt"]
        if r["total"] is None:
            return ["I read your receipt, but I could not read its total. What did you pay? Type it in the form under the receipt and I will count it."]
        if r["issued_on"] is None:
            return [
                f"I read your receipt of {_money(r['total'], cur)}, but I could not read its date. On what day was it? "
                "Type it in the form under the receipt and I will count it if it is from this pay cycle."
            ]
        when = f", dated {r['issued_on']}"
        if r["counted"]:
            return [f"I read your receipt of {_money(r['total'], cur)}{when} and counted it this cycle."]
        if r["matched_transaction"]:
            return [f"I read your receipt of {_money(r['total'], cur)}{when}; it is already on your bank statement, so it is counted once."]
        if r["verified"]:
            return [f"I read your receipt of {_money(r['total'], cur)}{when}; it is outside this pay cycle, so it does not change what you can spend now."]
        return [
            f"I read your receipt of {_money(r['total'], cur)}{when}, but it could not be verified, so it is not counted. "
            "If you know the right total or date, type it in the form under the receipt."
        ]
    text = []
    for item in d["statement"]["imports"]:
        st = item["statement"]
        text.append(
            f"I imported your statement for {st['period_start']} to {st['period_end']} with {st['line_count']} movements; "
            f"{item['ledger']['posted']} of them were added to your ledger."
        )
    return text


def _expense(p: Payload, cur: str) -> list[str]:
    d = p["data"]
    how = {"cash": ", paid in cash", "card": ", paid by card"}.get(d["payment"], "")
    kind = f", {d['category']}" if d["category"] != "uncategorized" else ""
    return [f"I prepared the expense: {_money(d['amount'], cur)} on {d['spent_on']}{how}{kind}. Check it and confirm it in the card below; nothing is saved until you do."]


_MARKDOWN = re.compile(r"\*\*|__|`|^\s*(?:#+|[-*>]|\d+[.)])\s+", re.M)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(¿¡A-ZÁÉÍÓÚÑ])")


def _passage_sentences(text: str) -> list[str]:
    """The passage as plain sentences: headings dropped, Markdown marks removed, whitespace collapsed."""
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    plain = re.sub(r"\s+", " ", " ".join(_MARKDOWN.sub("", line).strip() for line in lines)).strip()
    return [s for s in _SENTENCE_END.split(plain) if s]


def _concepts(p: Payload, cur: str) -> list[str]:
    """The top passage, deterministically: its title, its first sentences and the not-advice sentence.

    Card text is untrusted data: it is quoted, never obeyed. A sentence with a figure that is not a fact of the
    payload is left out, so the narration always passes the verifier.
    """
    top = p["data"]["concepts"][0]
    lang = top["lang"] if top["lang"] in NOT_ADVICE_SENTENCE else "en"
    facts = tuple(Fact(**f) for f in p.get("facts", ()))
    sentences = _passage_sentences(top["passage"]["untrusted_text"])
    kept = [s for s in sentences if verify_explanation(s, facts, (), money_units=frozenset({cur})).ok]
    body = " ".join(kept[:MAX_PASSAGE_SENTENCES])
    title = " ".join(str(top["title"]).split())
    return [f"{title}: {body}" if body else f"{title}.", NOT_ADVICE_SENTENCE[lang]]


def _fact(payload: Payload, key: str) -> Any:
    for fact in payload.get("facts", ()):
        if fact["key"] == key:
            return fact["value"]
    raise KeyError(key)


_HANDLERS = {
    "get_financial_state": _financial_state,
    "get_commitments": _commitments,
    "forecast_cashflow": _forecast,
    "simulate_purchase": _purchase,
    "compute_protected_surplus": _surplus,
    "assess_financial_capacity": _capacity,
    "assess_risk_tolerance": _tolerance,
    "derive_permitted_profile": _permitted,
    "compute_savings_plan": _plan,
    "propose_savings_rule": _action,
    "propose_liquidity_floor": _action,
    "execute_sandbox_action": _action,
    "get_pending_actions": _pending,
    "get_audit_events": _audit,
    "get_user_profile": _profile,
    "get_spending_status": _spending,
    "get_latest_document": _document,
    "propose_expense": _expense,
    "search_financial_concepts": _concepts,
}
_SAYS_ITS_OWN_CAVEATS = {"search_financial_concepts"}  # the not-advice sentence, in the card's language
