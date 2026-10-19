/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * The confirmation contract (Spec v0 section 5). The UI shows exactly these terms and execution must match them exactly. The amount comes from a stored plan snapshot (create_savings_rule) or from the user's own message (set_liquidity_floor, ADR-037), never from model text. A set_liquidity_floor moves no money: source and destination are both the account it protects (checking).
 */
export interface ActionTerms {
  action: "create_savings_rule" | "set_liquidity_floor";
  amount: number;
  currency: string;
  frequency: "monthly";
  source_account: string;
  destination: string;
  effective_date: string;
}
