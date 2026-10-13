/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of get_financial_state.
 */
export interface FinancialState {
  user_id: string;
  currency: string;
  as_of: string;
  first_cycle: string;
  checking: number;
  reserve: number;
  goal_buckets: {
    [k: string]: number;
  };
  income_type: "salaried" | "freelance";
  active_rules: number;
}
