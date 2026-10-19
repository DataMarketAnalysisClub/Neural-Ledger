---
{
  "id": "protected_surplus",
  "lang": "en",
  "title": "Protected surplus",
  "aliases": ["what is really available", "available money", "excedente protegido"],
  "tags": ["neural ledger", "cash flow", "saving"],
  "related": ["liquidity_floor", "emergency_fund", "installments"],
  "sources": [
    {"title": "Neural Ledger Financial Core", "url": "https://github.com/DataMarketAnalysisClub/Neural-Ledger/blob/main/docs/FINANCIAL_CORE.md", "license": "project documentation"}
  ],
  "numbers": []
}
---
Your protected surplus is the money that could leave your account today without any month of the conservative forecast falling below your minimum balance.

It is not the balance you see in your account. Part of that balance is already promised: rent, bills, card payments and the installments (cuotas) of past purchases that will fall due in the coming months. The protected surplus looks ahead over the forecast horizon, subtracts what is already committed, and keeps a cushion for the months that usually cost more than average.

The forecast is conservative on purpose. It assumes your income arrives a little lower and your spending a little higher than usual, so the figure is lower than a simple "income minus spending" calculation.

Two things move it:

- New commitments, such as a purchase in cuotas, lower it in every month they are paid.
- A higher minimum balance (your liquidity floor) lowers it too, because more money has to stay in the account.

The protected surplus is an estimate from your own history, not a promise about the future. It is general information about how the copilot measures what is available, not a recommendation to spend or save a specific amount.
