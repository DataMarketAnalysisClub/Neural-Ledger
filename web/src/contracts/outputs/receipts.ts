/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of GET /v1/receipts (ADR-039): the user's receipts in import order, personal data removed.
 */
export type Receipts = Receipt[];

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
