/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Read the user's current balances: checking (the balance just before the next payday), the reserve bucket and goal buckets. Use it when the user asks what they have right now. It does not forecast anything; use forecast_cashflow for the future.
 */
export interface GetFinancialStateInput {}
