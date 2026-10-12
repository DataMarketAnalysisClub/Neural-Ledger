/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of simulate_purchase.
 */
export interface PurchaseSimulation {
  quote: {
    principal: number;
    installments: number;
    monthly_rate: number;
    rate_assumed: boolean;
    installment: number;
    total_cost: number;
    total_interest: number;
    /**
     * (1 + r)^12 - 1 as a fraction. Not labelled CAE.
     */
    effective_annual_rate: number;
  };
  first_installment_month: string;
  horizon_months: number;
  verdict: "BASELINE_BREACH" | "FITS_ALL" | "FITS_TYPICAL_ONLY" | "BREACHES_ALL";
  impacts: {
    scenario: "typical" | "conservative";
    lowest_headroom_before: number;
    lowest_headroom_after: number;
    binding_month_after: string;
    trough_after_in_binding_month: number;
    breaches_after: string[];
  }[];
  /**
   * @maxItems 3
   */
  alternatives: {
    kind: "defer_start" | "change_installments" | "reduce_amount";
    amount: number;
    installments: number;
    first_installment_month: string;
    installment: number;
    total_cost: number;
    total_interest: number;
  }[];
}
