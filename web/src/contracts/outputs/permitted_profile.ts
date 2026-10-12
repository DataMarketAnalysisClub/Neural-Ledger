/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of derive_permitted_profile: permitted = min(tolerance, capacity) + hard rules.
 */
export interface PermittedProfile {
  permitted: "conservative" | "moderate" | "aggressive";
  tolerance: "conservative" | "moderate" | "aggressive";
  capacity: "conservative" | "moderate" | "aggressive";
  hard_rules_triggered: string[];
}
