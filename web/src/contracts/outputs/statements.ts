/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of GET /v1/statements: the user's imported statements, oldest import first.
 */
export type Statements = Summary[];

export interface Summary {
  statement_id: string;
  /**
   * Code of the Bank layout that read it, e.g. santander_cl_cuentamatica.
   */
  bank: string;
  /**
   * Masked at import: only the last 4 digits are kept, e.g. ****3456 (ADR-028).
   */
  account_ref: string;
  currency: string;
  period_start: string;
  period_end: string;
  source: "text" | "ocr";
  imported_at: string;
  line_count: number;
  /**
   * Sum of charges read from the lines (positive).
   */
  total_debits: number;
  total_credits: number;
  /**
   * As printed.
   */
  opening_balance: number | null;
  /**
   * As printed.
   */
  closing_balance: number | null;
  /**
   * True only if every printed total and daily balance matched the lines.
   */
  verified: boolean;
  issues: {
    code:
      | "TOTAL_DEBITS"
      | "TOTAL_CREDITS"
      | "CLOSING_BALANCE"
      | "DAILY_BALANCE"
      | "OUT_OF_PERIOD"
      | "NO_SUMMARY"
      | "LOW_CONFIDENCE";
    message: string;
    expected: number | null;
    found: number | null;
    on: string | null;
  }[];
}
