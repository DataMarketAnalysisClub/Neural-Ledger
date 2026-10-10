"""Stage 1: ledger snapshot -> FinancialModel (Financial Core 4.1 to 4.3).  OWNER: Role A.

The output is exactly the FinancialModel the persona fixture loader builds, so stage 2
(forecast, surplus, plan, capacity, purchase) cannot tell the two sources apart.

Months are PAY CYCLES (paycycle.py): cycle M runs from payday(M-1) to the day before
payday(M), the same labelling forecast.py uses. as_of must be the day before a payday;
partial cycles are out of scope and return INVALID_INPUT.

4.1 Commitments
    Installments: structured metadata first (confidence 1.0), "CUOTA nn/NN" parsed from the
    card line as fallback (params.installment_parsed_confidence). A cuota line with neither
    stays in variable spend with an INSTALLMENT_UNPARSED warning. Plans whose last cuota is
    before the first projected cycle have ended and are not commitments.
    Recurring items: same counterparty and category, >= 3 hits in the last 6 cycles, 28-35 days
    apart, every amount within 5% of the last one; amount = last observed; confidence =
    cycles present / cycles expected since the first occurrence in the window (< 0.8 -> stays
    in variable spend). No occurrence for 45 days -> ended: not a commitment, and its history
    stays in variable spend (the conservative choice, design principle 3). commitment_id = the category, suffixed with the counterparty
    slug when one category has several recurring counterparties.
4.2 Income
    Salaried: contracted net, cross-checked against the median of the last 3 salary credits;
    if they differ by more than 5%, the lower one. A missing salary credit in the last 3
    cycles -> contracted net and a SALARY_MISSING warning. Freelance: per-cycle totals over the
    window with zero cycles included; typical = P50, conservative = P20, CV with the sample
    standard deviation (params.income_cv_ddof). Bonuses are never income.
4.3 Spend
    Per category, per-cycle totals over the window: purchases and fees, minus refunds, never
    below 0 per category-cycle. transfer_own (card payments, savings sweeps), cuota lines and
    recurring commitments are excluded. P50 and P80 are linear-interpolation quantiles
    (numpy method="linear") over the non-seasonal cycles. Seasonal factor for each flagged
    month = last year's total / sum of category P50s, clamped to [1, 2]. Deviation from the
    design doc section 3 (docs/SCOPE.md F9): one factor per month, not per category, because
    SpendModel applies a single factor to the summed quantiles. Categories with fewer than 6
    observed cycles are merged into "other" (essential if any merged category was) and flagged.
Duplicates: exact txn_id duplicates are dropped; same date, amount and counterparty is
flagged and kept (it can be two real purchases). Merchant text is data only: it feeds the
category lookup and the untrusted `label` field, and never appears in a warning message.
H4: fewer than params.min_history_months cycles -> INSUFFICIENT_DATA with `missing`.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction

from ..ledger.entities import (
    AccountType,
    IncomeType,
    LedgerSnapshot,
    Transaction,
    TransactionKind,
)
from ..shared.envelope import Caveat, Envelope, Fact
from ..shared.hashing import content_id
from ..shared.month import Month, month_range
from ..shared.numbers import round_half_up
from .model import (
    Balances,
    CategorySpend,
    Commitment,
    CommitmentType,
    FinancialModel,
    IncomeModel,
    SpendModel,
)
from .params import FinanceParams
from .paycycle import cycle_of, is_eve_of_payday

SALARY_CATEGORY = "salary"
BONUS_CATEGORIES = frozenset({"bonus"})
OTHER_CATEGORY = "other"
UNCATEGORIZED = frozenset({"", "uncategorized"})
SPEND_KINDS = frozenset({TransactionKind.PURCHASE, TransactionKind.FEE})
RECURRING_TYPES = {"rent": CommitmentType.RENT, "loan": CommitmentType.LOAN}

# Category lookup for lines the ledger left uncategorized. Keys are normalized counterparties.
MERCHANT_CATEGORIES: dict[str, str] = {
    "lider express": "groceries",
    "jumbo": "groceries",
    "unimarc": "groceries",
    "santa isabel": "groceries",
    "starbucks": "dining",
    "copec": "transport",
    "uber": "transport",
    "metro bip": "transport",
    "enel": "utilities",
    "aguas andinas": "utilities",
    "cruz verde": "health",
    "salcobrand": "health",
}

_CUOTA_NUMBERS = re.compile(r"\bCUOTA\s*(\d{1,2})\s*/\s*(\d{1,2})\b", re.IGNORECASE)
_CUOTA_WORD = re.compile(r"\bCUOTA\b", re.IGNORECASE)
_SLUG = re.compile(r"[^a-z0-9]+")


# ---- exact statistics -----------------------------------------------------------------------


def quantile(values: Sequence[int | Fraction], q: Fraction) -> Fraction:
    """Empirical quantile with linear interpolation (numpy.quantile, method="linear")."""
    if not values:
        raise ValueError("quantile of an empty sequence")
    if not 0 <= q <= 1:
        raise ValueError("q must be in [0, 1]")
    ordered = sorted(Fraction(v) for v in values)
    position = q * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _sqrt(value: Fraction) -> Fraction:
    """Exact square root when it is rational; otherwise a 28-digit Decimal approximation."""
    if value < 0:
        raise ValueError("square root of a negative number")
    num, den = math.isqrt(value.numerator), math.isqrt(value.denominator)
    if num * num == value.numerator and den * den == value.denominator:
        return Fraction(num, den)
    with localcontext() as ctx:
        ctx.prec = 28
        root = (Decimal(value.numerator) / Decimal(value.denominator)).sqrt()
    return Fraction(root)


def coefficient_of_variation(values: Sequence[int], ddof: int) -> Fraction:
    n = len(values)
    if n - ddof <= 0:
        raise ValueError("not enough values for the requested ddof")
    mean = Fraction(sum(values), n)
    if mean == 0:
        raise ValueError("coefficient of variation of a zero-mean series")
    variance = sum((Fraction(v) - mean) ** 2 for v in values) / (n - ddof)
    return _sqrt(variance / (mean * mean))


# ---- helpers --------------------------------------------------------------------------------


def _counterparty(text: str) -> str:
    return " ".join(text.split()).casefold()


def _slug(text: str) -> str:
    return _SLUG.sub("-", text.casefold()).strip("-")[:24] or "item"


def _category(txn: Transaction) -> str:
    category = (txn.category or "").strip().lower()
    if category in UNCATEGORIZED:
        return MERCHANT_CATEGORIES.get(_counterparty(txn.merchant_raw), OTHER_CATEGORY)
    return category


def _caveat(code: str, message: str) -> Caveat:
    return Caveat(code, message)


@dataclass(frozen=True, slots=True)
class _CuotaLine:
    txn: Transaction
    cycle: Month
    plan_key: str
    commitment_id: str
    label: str
    number: int
    total: int
    confidence: Fraction


def _parse_cuota(txn: Transaction, cycle: Month, params: FinanceParams) -> _CuotaLine | None:
    label = " ".join(_CUOTA_NUMBERS.sub(" ", txn.merchant_raw).split())
    if txn.installment is not None:
        info = txn.installment
        return _CuotaLine(txn, cycle, f"plan:{info.plan_id}", info.plan_id, label, info.installment_number, info.installment_total, Fraction(1))
    match = _CUOTA_NUMBERS.search(txn.merchant_raw)
    if match is None:
        return None
    number, total = int(match.group(1)), int(match.group(2))
    if not 1 <= number <= total:
        return None
    return _CuotaLine(txn, cycle, f"text:{_counterparty(label)}", _slug(label), label, number, total, params.installment_parsed_confidence)


# ---- the estimator --------------------------------------------------------------------------


def estimate_model(snapshot: LedgerSnapshot, params: FinanceParams) -> Envelope[FinancialModel]:
    version = params.version
    if not is_eve_of_payday(snapshot.as_of):
        return Envelope.invalid(
            "as_of", (), params_version=version,
            message="as_of must be the day before a payday (last weekday of the month); partial cycles are not supported",
        )
    last_cycle = cycle_of(snapshot.as_of)
    first_cycle = last_cycle.plus(1)
    warnings: list[Caveat] = []

    # duplicates -------------------------------------------------------------------------------
    seen: set[str] = set()
    txns: list[Transaction] = []
    dropped = 0
    for txn in sorted(snapshot.transactions, key=lambda t: (t.date, t.txn_id)):
        if txn.date > snapshot.as_of:
            continue
        if txn.txn_id in seen:
            dropped += 1
            continue
        seen.add(txn.txn_id)
        txns.append(txn)
    if dropped:
        warnings.append(_caveat("DUPLICATE_TXN_ID", f"{dropped} transaction(s) with a repeated txn_id were ignored."))
    near: dict[tuple, list[str]] = defaultdict(list)
    for txn in txns:
        near[(txn.account_id, txn.date, txn.amount, _counterparty(txn.merchant_raw))].append(txn.txn_id)
    flagged = sorted(ids for ids in near.values() if len(ids) > 1)
    if flagged:
        warnings.append(_caveat(
            "NEAR_DUPLICATE",
            f"{len(flagged)} group(s) of transactions share date, amount and counterparty and were kept: "
            + "; ".join(",".join(ids) for ids in flagged),
        ))

    # history and window ------------------------------------------------------------------------
    if not txns:
        return Envelope.insufficient(("transactions",), params_version=version, message="the ledger has no transactions")
    earliest = cycle_of(txns[0].date)
    history = earliest.months_until(last_cycle) + 1
    if history < params.min_history_months:
        return Envelope.insufficient(
            (f"history (at least {params.min_history_months} months, found {history})",),
            params_version=version, message="not enough history to estimate the financial model",
        )
    window_start = max(earliest, last_cycle.plus(-(params.spend_window_months - 1)))
    window = month_range(window_start, window_start.months_until(last_cycle) + 1)
    in_window = [(t, cycle_of(t.date)) for t in txns if cycle_of(t.date) >= window_start]

    # 4.1 installments ---------------------------------------------------------------------------
    cuota_lines: list[_CuotaLine] = []
    cuota_txn_ids: set[str] = set()
    unparsed = 0
    for txn, cycle in in_window:
        if txn.kind not in SPEND_KINDS or txn.amount >= 0:
            continue
        if txn.installment is None and not _CUOTA_WORD.search(txn.merchant_raw):
            continue
        line = _parse_cuota(txn, cycle, params)
        if line is None:
            unparsed += 1
            continue
        cuota_lines.append(line)
        cuota_txn_ids.add(txn.txn_id)
    if unparsed:
        warnings.append(_caveat(
            "INSTALLMENT_UNPARSED",
            f"{unparsed} installment line(s) had no metadata and no readable CUOTA nn/NN; they were counted as variable spend.",
        ))
    commitments: list[Commitment] = []
    plans: dict[str, list[_CuotaLine]] = defaultdict(list)
    for line in cuota_lines:
        plans[line.plan_key].append(line)
    for lines in plans.values():
        latest = max(lines, key=lambda l: (l.cycle, l.number))
        first_due = latest.cycle.plus(-(latest.number - 1))
        last_due = latest.cycle.plus(latest.total - latest.number)
        if last_due < first_cycle:
            continue  # the plan has ended
        commitments.append(Commitment(
            commitment_id=latest.commitment_id,
            type=CommitmentType.INSTALLMENT,
            label=latest.label,
            amount=-latest.txn.amount,
            first_due=first_due,
            last_due=last_due,
            confidence=float(latest.confidence),
            installments_total=latest.total,
            evidence_txn_ids=tuple(l.txn.txn_id for l in sorted(lines, key=lambda l: (l.txn.date, l.txn.txn_id))),
        ))

    # 4.1 recurring items ------------------------------------------------------------------------
    groups: dict[tuple[str, str], list[tuple[Transaction, Month]]] = defaultdict(list)
    for txn, cycle in in_window:
        if txn.kind in SPEND_KINDS and txn.amount < 0 and txn.txn_id not in cuota_txn_ids:
            groups[(_category(txn), _counterparty(txn.merchant_raw))].append((txn, cycle))
    lookback_start = last_cycle.plus(-(params.recurring_lookback_months - 1))
    low_days, high_days = params.recurring_interval_days
    recurring: list[tuple[str, list[tuple[Transaction, Month]]]] = []
    recurring_txn_ids: set[str] = set()
    for (category, _), occurrences in sorted(groups.items()):
        recent = [(t, c) for t, c in occurrences if c >= lookback_start]
        if len(recent) < params.recurring_min_hits:
            continue
        intervals = [(b[0].date - a[0].date).days for a, b in zip(recent, recent[1:])]
        if not all(low_days <= d <= high_days for d in intervals):
            continue
        last_amount = -recent[-1][0].amount
        if not all(abs(-t.amount - last_amount) <= params.recurring_amount_tolerance * last_amount for t, _ in recent):
            continue
        first_seen = occurrences[0][1]
        expected = first_seen.months_until(last_cycle) + 1
        present = len({c for _, c in occurrences})
        if (snapshot.as_of - recent[-1][0].date).days > params.recurring_end_days:
            continue  # ended: not a commitment; its history stays in variable spend (conservative)
        if Fraction(present, expected) < params.commitment_confidence_cutoff:
            continue  # stays in variable spend, where P80 covers it
        recurring.append((category, occurrences))
        recurring_txn_ids.update(t.txn_id for t, _ in occurrences)
    per_category: dict[str, int] = defaultdict(int)
    for category, _ in recurring:
        per_category[category] += 1
    for category, occurrences in recurring:
        last_txn = occurrences[-1][0]
        suffix = f"-{_slug(last_txn.merchant_raw)}" if per_category[category] > 1 else ""
        expected = occurrences[0][1].months_until(last_cycle) + 1
        commitments.append(Commitment(
            commitment_id=f"{category}{suffix}",
            type=RECURRING_TYPES.get(category, CommitmentType.SUBSCRIPTION),
            label=" ".join(last_txn.merchant_raw.split()),
            amount=-last_txn.amount,
            first_due=occurrences[0][1],
            last_due=None,
            confidence=float(Fraction(len({c for _, c in occurrences}), expected)),
            installments_total=None,
            evidence_txn_ids=tuple(t.txn_id for t, _ in occurrences),
        ))

    # 4.2 income ---------------------------------------------------------------------------------
    income = _income_model(snapshot, params, in_window, window, last_cycle, warnings)
    if isinstance(income, Envelope):
        return income

    # 4.3 spend ----------------------------------------------------------------------------------
    excluded = cuota_txn_ids | recurring_txn_ids
    debits = [(t, c) for t, c in in_window if t.kind in SPEND_KINDS and t.amount < 0 and t.txn_id not in excluded]
    refunds = [(t, c) for t, c in in_window if t.kind is TransactionKind.REFUND and t.amount > 0]
    spend = _spend_model(params, window, debits, refunds, warnings)
    if isinstance(spend, Envelope):
        return spend
    one_off = max((-t.amount for t, _ in debits if not _CUOTA_WORD.search(t.merchant_raw)), default=0)

    # balances and model ---------------------------------------------------------------------
    checking = sum(a.balance for a in snapshot.accounts if a.type is AccountType.CHECKING)
    buckets = {b.bucket: b.amount for b in snapshot.buckets}
    goal_buckets = {k.split(":", 1)[1]: v for k, v in buckets.items() if k.startswith("goal:")}
    source_version = f"ledger:{snapshot.user_id}:{snapshot.ledger_version}"
    model = FinancialModel(
        user_id=snapshot.user_id,
        currency=snapshot.currency,
        as_of=snapshot.as_of,
        first_cycle=first_cycle,
        balances=Balances(checking=checking, reserve=buckets.get("reserve", 0), goal_buckets=goal_buckets),
        income=income,
        commitments=tuple(sorted(commitments, key=lambda c: (c.first_due, c.commitment_id))),
        spend=spend,
        goals=snapshot.goals,
        source_version=source_version,
        largest_one_off_expense=one_off,
    )
    missing = model.missing_fields()
    if missing:
        return Envelope.insufficient(missing, params_version=version, message="financial state is incomplete")
    facts = (
        Fact("estimate.income.typical", income.typical, snapshot.currency, f"income model ({income.method})"),
        Fact("estimate.income.conservative", income.conservative, snapshot.currency, f"income model ({income.method})"),
        Fact("estimate.spend.p50_total", sum(c.p50 for c in spend.categories), snapshot.currency, "sum of category P50"),
        Fact("estimate.spend.p80_total", sum(c.p80 for c in spend.categories), snapshot.currency, "sum of category P80"),
        Fact("estimate.commitments", len(commitments), "count", "installments + recurring items"),
    )
    return Envelope.success(
        model,
        params_version=version,
        snapshot_id=content_id("model", source_version, snapshot.as_of, version),
        as_of=snapshot.as_of.isoformat(),
        facts=facts,
        warnings=tuple(warnings),
    )


def _income_model(
    snapshot: LedgerSnapshot,
    params: FinanceParams,
    in_window: Sequence[tuple[Transaction, Month]],
    window: Sequence[Month],
    last_cycle: Month,
    warnings: list[Caveat],
) -> IncomeModel | Envelope[FinancialModel]:
    credits = [
        (t, c) for t, c in in_window
        if t.kind is TransactionKind.INCOME and t.amount > 0 and _category(t) not in BONUS_CATEGORIES
    ]
    profile = snapshot.income_profile
    if profile.type is IncomeType.SALARIED and profile.contracted_net:
        contracted = profile.contracted_net
        salary = [(t, c) for t, c in credits if _category(t) == SALARY_CATEGORY]
        recent_cycles = {last_cycle.plus(-k) for k in range(3)}
        if not recent_cycles <= {c for _, c in salary}:
            warnings.append(_caveat("SALARY_MISSING", "A salary credit is missing in the last 3 cycles; contracted income was used."))
            value = contracted
        else:
            median = quantile([t.amount for t, _ in salary[-3:]], Fraction(1, 2))
            value = contracted
            if abs(median - contracted) > Fraction(5, 100) * contracted:
                value = min(contracted, round_half_up(median))
                warnings.append(_caveat("SALARY_DIFFERS", "Recent salary credits differ from the contracted net by more than 5%; the lower was used."))
        return IncomeModel(IncomeType.SALARIED, value, value, Fraction(0), "contracted")

    if profile.type is IncomeType.SALARIED:
        warnings.append(_caveat("CONTRACT_UNKNOWN", "No contracted net income; income was estimated from percentiles."))
    totals = defaultdict(int)
    for t, c in credits:
        totals[c] += t.amount
    series = [totals[c] for c in window]  # zero cycles included
    if sum(series) <= 0:
        return Envelope.insufficient(("income",), params_version=params.version, message="no income credits in the window")
    return IncomeModel(
        type=profile.type,
        typical=round_half_up(quantile(series, Fraction(1, 2))),
        conservative=round_half_up(quantile(series, Fraction(params.conservative_income_percentile, 100))),
        cv=coefficient_of_variation(series, params.income_cv_ddof),
        method="percentile",
    )


def _spend_model(
    params: FinanceParams,
    window: Sequence[Month],
    debits: Iterable[tuple[Transaction, Month]],
    refunds: Iterable[tuple[Transaction, Month]],
    warnings: list[Caveat],
) -> SpendModel | Envelope[FinancialModel]:
    gross: dict[str, dict[Month, int]] = defaultdict(lambda: defaultdict(int))
    refunded: dict[str, dict[Month, int]] = defaultdict(lambda: defaultdict(int))
    for t, c in debits:
        gross[_category(t)][c] += -t.amount
    for t, c in refunds:
        refunded[_category(t)][c] += t.amount
    monthly = {
        cat: {c: max(0, gross[cat][c] - refunded[cat][c]) for c in window}
        for cat in gross
    }
    observed = {cat: sum(1 for c in window if gross[cat][c] > 0) for cat in gross}
    sparse = sorted(cat for cat, n in observed.items() if n < params.min_history_months)
    essential = {cat: cat in params.essential_categories for cat in monthly}
    if sparse:
        merged = {c: sum(monthly[cat][c] for cat in sparse) for c in window}
        merged_essential = any(essential[cat] for cat in sparse)
        for cat in sparse:
            monthly.pop(cat)
        if OTHER_CATEGORY in monthly:
            merged = {c: merged[c] + monthly[OTHER_CATEGORY][c] for c in window}
            merged_essential = merged_essential or essential[OTHER_CATEGORY]
        monthly[OTHER_CATEGORY] = merged
        essential[OTHER_CATEGORY] = merged_essential
        warnings.append(_caveat(
            "CATEGORY_SPARSE",
            f"{len(sparse)} categor{'y' if len(sparse) == 1 else 'ies'} with fewer than {params.min_history_months} months of data "
            f"({', '.join(sparse)}) were modelled together as '{OTHER_CATEGORY}'.",
        ))

    base_cycles = [c for c in window if c.month not in params.seasonal_months]
    if not base_cycles or not monthly:
        return Envelope.insufficient(("spend.categories",), params_version=params.version, message="no variable spend in the window")
    p_conservative = Fraction(params.variable_spend_percentile, 100)
    categories = tuple(
        CategorySpend(
            category=cat,
            p50=round_half_up(quantile([monthly[cat][c] for c in base_cycles], Fraction(1, 2))),
            p80=round_half_up(quantile([monthly[cat][c] for c in base_cycles], p_conservative)),
            essential=essential[cat],
        )
        for cat in sorted(monthly)
    )
    base = sum(c.p50 for c in categories)
    factors: dict[int, Fraction] = {}
    for month_number in params.seasonal_months:
        seasonal = [c for c in window if c.month == month_number]
        if seasonal and base > 0:
            last = seasonal[-1]
            raw = Fraction(sum(monthly[cat][last] for cat in monthly), base)
            factors[month_number] = min(params.seasonal_factor_max, max(params.seasonal_factor_min, raw))
    return SpendModel(categories=categories, seasonal_factors=factors, window_months=len(window))
