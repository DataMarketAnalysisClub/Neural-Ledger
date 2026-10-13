/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Compute the protected surplus: how much could leave checking today without any conservative trough falling below the liquidity floor over the horizon, plus the free monthly flow. Never call this amount 'safe'.
 */
export interface ComputeProtectedSurplusInput {
  horizon_months?: number;
  include_plan?: "none" | "recommended" | "active";
}
