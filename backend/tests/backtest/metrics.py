"""Finite-sample summaries for the synthetic backtest (docs/BACKTEST.md).

Two kinds, never mixed:
  * Bernoulli rates (coverage: did the realized value fall inside the estimated bound?) get
    a Wilson 95% score interval. Trials of one seed share data across origins and categories,
    so the interval assumes an independence the design does not have: it is optimistic.
  * Continuous quantities (relative errors, parameter recovery) get n, median, p10, p90 and
    the mean absolute value. No interval: a Wilson interval is meaningless for them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import NormalDist

Z95 = NormalDist().inv_cdf(0.975)
BERNOULLI = "bernoulli_rate"
CONTINUOUS = "continuous_summary_no_interval"


def _r(x: float) -> float:
    return round(x, 6)


def wilson(hits: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion hits/n."""
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ValueError("a Wilson interval needs at least one trial")
    if not 0 <= hits <= n:
        raise ValueError("hits must be between 0 and n")
    p = hits / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def coverage(outcomes: Sequence[bool], nominal: float | None = None) -> dict:
    n, hits = len(outcomes), sum(1 for o in outcomes if o)
    out: dict = {"kind": BERNOULLI, "n": n, "hits": hits, "nominal": nominal}
    if n == 0:
        return {**out, "rate": None, "wilson95": None}
    low, high = wilson(hits, n)
    return {**out, "rate": _r(hits / n), "wilson95": [_r(low), _r(high)]}


def quantile(ordered: Sequence[float], q: float) -> float:
    """Linear interpolation on sorted values (the estimator's own quantile definition)."""
    position = q * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summary(values: Sequence[float]) -> dict:
    n = len(values)
    out: dict = {"kind": CONTINUOUS, "n": n}
    if n == 0:
        return {**out, "median": None, "p10": None, "p90": None, "mean_abs": None}
    ordered = sorted(values)
    return {
        **out,
        "median": _r(quantile(ordered, 0.5)),
        "p10": _r(quantile(ordered, 0.1)),
        "p90": _r(quantile(ordered, 0.9)),
        "mean_abs": _r(sum(abs(v) for v in values) / n),
    }
