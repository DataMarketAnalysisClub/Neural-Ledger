/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Execute an action the user already confirmed, by its authorization_id (see get_pending_actions). The terms are read from the stored authorization. If you pass requested_terms they are only compared: any difference from what the user authorized is blocked and logged. Expired, reused or altered authorizations are blocked.
 */
export interface ExecuteSandboxActionInput {
  authorization_id: string;
  requested_terms?: {
    action: "create_savings_rule";
    amount: number;
    currency: string;
    frequency: "monthly";
    source_account: string;
    destination: string;
    effective_date: string;
  } | null;
}
