/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of POST /v1/statements. Personal data is removed before anything is stored (ADR-028). An unverified statement is still stored but not posted to the transaction ledger; a duplicate stores nothing new.
 */
export interface StatementImport {
  duplicate: boolean;
  statement: Summary;
  /**
   * How personal data was removed from this import. Null for a duplicate: nothing new was redacted or stored.
   */
  redaction: {
    /**
     * Version of the built-in rules, which always run, e.g. pii-0.1.
     */
    rules: string;
    /**
     * Optional detector run after the rules (NL_PII_DETECTOR): none or azure_language.
     */
    detector: string;
    /**
     * True when the detector was unavailable and only the rules ran (see the REDACTION_DEGRADED warning).
     */
    degraded: boolean;
    /**
     * Placeholders inserted per code; codes with none are left out. Counts only, never the text they replaced.
     */
    counts: {
      [k: string]: number;
    };
  } | null;
  /**
   * Posting to the transaction ledger. posted = 0 and classifier = null when the statement was not posted (see the NOT_POSTED warning).
   */
  ledger: {
    /**
     * Transactions this statement contributes to the ledger.
     */
    posted: number;
    /**
     * Of those, added by this import (0 on a re-import).
     */
    new: number;
    /**
     * Charges whose category was not accepted.
     */
    uncategorized: number;
    /**
     * Method and training-data hash that chose the categories, e.g. naive_bayes@3f2a9c1d04be.
     */
    classifier: string | null;
  };
}
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
