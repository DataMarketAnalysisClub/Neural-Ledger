/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of GET /v1/spending and of the copilot's get_spending_status tool (T0, ADR-039): the spending check-in for the first projected cycle and the latest receipt. Receipts a statement charge already records are counted once, as that charge.
 */
export interface SpendingStatus {
  check: SpendingCheck;
  latest_receipt: Receipt | null;
  receipts_counted: number;
  receipts_matched: number;
}
export interface SpendingCheck {
  cycle: string;
  window_start: string;
  /**
   * The eve of the next payday: the cycle runs from window_start (payday) to here.
   */
  window_end: string;
  /**
   * The forecast projects this cycle, so an overspend lowers the protected surplus; false for a cycle before the forecast's first one.
   */
  projected: boolean;
  today: string;
  days_left: number;
  /**
   * Conservative (P80) variable spending the forecast counts on for the cycle, CLP.
   */
  assumed: number;
  logged: number;
  logged_items: number;
  /**
   * assumed - logged; negative once spending passed the assumption.
   */
  left: number;
  /**
   * left // days_left, rounded down; 0 once nothing is left.
   */
  per_day: number;
  overspend: number;
  protected_surplus: number;
  /**
   * protected_surplus - overspend in a projected cycle (else protected_surplus); negative means a conservative month breaches the floor.
   */
  surplus_after: number;
  categories: {
    category: string;
    assumed: number;
    logged: number;
  }[];
}
export interface Receipt {
  receipt_id: string;
  issuer: {
    untrusted_text: string;
  };
  issued_on: string | null;
  total: number | null;
  currency: "CLP";
  folio: string | null;
  /**
   * The SII stamp (timbre electrónico) was decoded and confirms the print.
   */
  stamped: boolean;
  /**
   * manual: an expense the user told the copilot about and confirmed.
   */
  source: "text" | "ocr" | "manual";
  /**
   * Cash is never matched with a statement charge.
   */
  payment: "cash" | "card" | "unknown";
  category: string;
  classifier: string;
  /**
   * Only a verified receipt is counted.
   */
  verified: boolean;
  issues: {
    code: "TOTAL_MISSING" | "DATE_MISSING" | "DATE_IN_FUTURE" | "TAX_MISMATCH" | "STAMP_MISMATCH";
    message: string;
  }[];
  /**
   * The statement charge that already records this purchase: the receipt is then counted once, as that charge.
   */
  matched_transaction: string | null;
  duplicate: boolean;
  /**
   * The user typed or confirmed its total or date in the app.
   */
  corrected: boolean;
  /**
   * Part of this cycle's logged spending: verified, not on a statement, dated inside the cycle. A receipt from an earlier cycle is kept but does not change today's figure.
   */
  counted: boolean;
}
