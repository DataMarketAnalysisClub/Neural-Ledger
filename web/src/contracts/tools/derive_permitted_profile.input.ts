/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Combine tolerance (what the user accepts) and capacity (what the finances permit): permitted = the lower of the two, plus hard rules. Pass the tolerance returned by assess_risk_tolerance.
 */
export interface DerivePermittedProfileInput {
  tolerance: "conservative" | "moderate" | "aggressive";
}
