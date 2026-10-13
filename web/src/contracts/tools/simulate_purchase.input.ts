/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Check whether a purchase paid in cuotas (installments) fits the user's future commitments. Returns the cuota, total cost, interest and effective annual rate, a verdict (FITS_ALL, FITS_TYPICAL_ONLY, BREACHES_ALL or BASELINE_BREACH) and up to three deterministic alternatives that fit. If the user does not say when the first cuota is billed, omit first_installment_month and the next month is assumed (and flagged). If no rate is given, a default monthly rate is assumed and flagged.
 */
export interface SimulatePurchaseInput {
  /**
   * Price in minor units of the user's currency.
   */
  amount: number;
  installments: 3 | 6 | 12 | 18 | 24;
  first_installment_month?: string;
  /**
   * Monthly interest rate as a fraction, e.g. 0.025.
   */
  monthly_rate?: number;
  include_plan?: "none" | "recommended" | "active";
}
