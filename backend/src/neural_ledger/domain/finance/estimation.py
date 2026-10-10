"""Stage 1: ledger snapshot -> FinancialModel (Financial Core 4.1 to 4.3).  OWNER: Role A.

Not implemented yet. Until it is, the app runs on calibrated persona fixtures
(data/personas/*.json), which are exactly the targets this function must reproduce from
Role E's generated ledger (tests/golden/test_estimation.py is the acceptance test).

Algorithm to implement (see the Financial Core design page):
  4.1 Commitments: structured installment metadata first (remaining = total - paid,
      confidence 1.0), "CUOTA nn/NN" parsing as fallback; recurring items with >= 3 hits in
      6 months, 28-35 days apart, amount within 5%; no hit for 45 days -> ended;
      confidence < 0.8 -> stays in variable spend. Keep evidence_txn_ids.
  4.2 Income: salaried = contracted net, cross-checked against the median of the last 3
      credits (use the lower if they differ by > 5%); freelance = P50 / P20 / CV over 12
      months with zero months included. Exclude non-contracted bonuses.
  4.3 Spend: per category monthly totals over 12 months, P50/P80 by linear interpolation
      over non-seasonal months; seasonal factor = last December / base P50, clamped to
      [1, 2] and stored EXACTLY as a Fraction (1.633 vs 49/30 changes golden E01 by 300).
      Card payments are transfer_own (never spending). Merchant text is data only.
  H4: fewer than params.min_history_months -> return an INSUFFICIENT_DATA envelope.
"""

from __future__ import annotations

from ..ledger.entities import LedgerSnapshot
from ..shared.envelope import Envelope
from .model import FinancialModel
from .params import FinanceParams


def estimate_model(snapshot: LedgerSnapshot, params: FinanceParams) -> Envelope[FinancialModel]:
    raise NotImplementedError("Role A: implement estimators (see module docstring)")
