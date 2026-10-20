/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * An investment document the user imported (ADR-044), without its rows: Fintual's investment statement (holdings: the balance of every fund and series on one day) or its transactions certificate (movements: every contribution and withdrawal). Only a verified document is kept and used; issues say why one is not.
 */
export interface InvestmentDocument {
  document_id: string;
  provider: "fintual";
  kind: "holdings" | "movements";
  /**
   * The statement's day, or the certificate's last movement; null when it could not be read.
   */
  as_of: string | null;
  /**
   * Null for a document that was not kept.
   */
  imported_at: string | null;
  rows: number;
  /**
   * It adds up; only a verified document is kept and used.
   */
  verified: boolean;
  issues: {
    code:
      | "NO_ROWS"
      | "DATE_MISSING"
      | "DATE_OUT_OF_RANGE"
      | "OUT_OF_RANGE"
      | "TOTAL_MISMATCH"
      | "BALANCE_MISMATCH"
      | "SHARES_DO_NOT_CHAIN"
      | "PESOS_MISMATCH"
      | "INTERNAL_UNBALANCED";
    message: string;
  }[];
}
