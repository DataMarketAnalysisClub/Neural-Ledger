---
{
  "id": "liquidity_floor",
  "lang": "en",
  "title": "Liquidity floor",
  "aliases": ["minimum balance", "balance floor", "piso de liquidez"],
  "tags": ["neural ledger", "cash flow"],
  "related": ["protected_surplus", "liquidity", "emergency_fund", "budget"],
  "sources": [
    {"title": "Neural Ledger decisions (ADR-037)", "url": "https://github.com/DataMarketAnalysisClub/Neural-Ledger/blob/main/docs/DECISIONS.md", "license": "project documentation"}
  ],
  "numbers": []
}
---
The liquidity floor is the minimum balance you choose to keep in your account at all times. Money below that line is not treated as available for spending, even on a day when the balance looks high.

In Neural Ledger, the copilot can suggest a floor based on your history, but the number only takes effect when you confirm it in the app. You can raise it, lower it or keep the current one. The decision is always yours.

The floor affects your protected surplus. Because more money has to stay in the account, a higher floor lowers the protected surplus. It is a day-to-day planning tool, not a savings product or a promise, and it is different from an emergency fund, which is set aside for larger, unexpected costs.

This is general information, not a recommendation.
