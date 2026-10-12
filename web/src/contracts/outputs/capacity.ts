/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of assess_financial_capacity. Weakest band wins.
 */
export interface CapacityAssessment {
  level: "conservative" | "moderate" | "aggressive";
  binding_factor: string;
  binding_factors: string[];
  factors: {
    name: "reserve_coverage" | "income_stability" | "debt_service" | "conservative_headroom" | "stress_coverage";
    value: number;
    band: "low" | "medium" | "high";
    measure: string;
  }[];
  essentials_monthly: number;
  reserve_minimum: number;
  reserve_target: number;
}
