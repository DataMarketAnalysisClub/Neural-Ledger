/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * The confirmation contract (Spec v0 section 5). The UI shows exactly these terms and execution must match them exactly. The amount always comes from a stored plan snapshot, never from model text.
 */
export interface ActionTerms {
  action: "create_savings_rule";
  amount: number;
  currency: string;
  frequency: "monthly";
  source_account: string;
  destination: string;
  effective_date: string;
}
