/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Prepare a savings-rule proposal from a computed plan (by its snapshot_id). The amount and dates come from the stored plan, not from you. Nothing moves: the user must confirm the exact terms in the app's confirmation card.
 */
export interface ProposeSavingsRuleInput {
  plan_snapshot_id: string;
}
