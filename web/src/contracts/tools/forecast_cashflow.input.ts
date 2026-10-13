/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Project the balance just before each payday (the trough) for the coming months. 'typical' uses typical income and median spending; 'conservative' uses conservative income and 80th-percentile spending and is the one used for every decision; 'stress' adds one unexpected expense. A month breaches when its trough falls below the liquidity floor. include_plan adds the recommended or the active savings rule to the path.
 */
export interface ForecastCashflowInput {
  horizon_months?: number;
  scenario?: "typical" | "conservative" | "stress";
  include_plan?: "none" | "recommended" | "active";
}
