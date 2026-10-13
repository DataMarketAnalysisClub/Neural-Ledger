/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of forecast_cashflow. trough = balance just before payday; headroom = trough - floor; a month breaches when headroom < 0.
 */
export interface Forecast {
  scenario: "typical" | "conservative" | "stress";
  floor: number;
  opening_trough: number;
  /**
   * @minItems 1
   */
  cycles: {
    month: string;
    income: number;
    commitments: number;
    variable: number;
    available: number;
    plan: number;
    purchase: number;
    shock: number;
    trough: number;
    headroom: number;
  }[];
}
