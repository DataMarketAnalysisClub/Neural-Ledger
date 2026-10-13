/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of compute_protected_surplus. Never described as 'safe' money.
 */
export interface SurplusResult {
  protected_surplus: number;
  binding_month: string;
  horizon_months: number;
  plan_amount: number;
  plan_start: string | null;
  monthly_free_flow: {
    month: string;
    amount: number;
  }[];
  breaches: string[];
}
