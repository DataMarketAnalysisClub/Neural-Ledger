/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Size a fixed monthly savings rule that never pushes a conservative trough below the floor, and allocate it to the reserve and near-term goals. The profile you pass is capped at the user's permitted profile, which the system recomputes. Only proposes numbers; to prepare an action call propose_savings_rule with the returned snapshot_id.
 */
export interface ComputeSavingsPlanInput {
  permitted_profile?: "conservative" | "moderate" | "aggressive";
}
