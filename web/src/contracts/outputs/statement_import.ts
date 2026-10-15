/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of POST /v1/statements: one entry per statement in the file, in file order (a card statement PDF holds a national and an international one). Personal data is removed before anything is stored, and a statement that cannot be redacted fails the whole import (ADR-028). An unverified or provisional statement is still stored but not posted to the transaction ledger; a duplicate stores nothing new.
 */
export interface StatementImport {
  /**
   * @minItems 1
   */
  imports: Imported[];
}
export interface Imported {
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
  /**
   * From the layout that read it. A credit card statement carries obligations and its payments are never income.
   */
  account_type: "checking" | "savings" | "credit_card";
  currency: string;
  period_start: string;
  period_end: string;
  source: "text" | "ocr" | "xlsx";
  imported_at: string;
  line_count: number;
  /**
   * Sum of charges read from the lines (positive).
   */
  total_debits: number;
  total_credits: number;
  /**
   * As printed; a card's previous billed debt, negative.
   */
  opening_balance: number | null;
  /**
   * As printed; a card's billed debt, negative.
   */
  closing_balance: number | null;
  /**
   * Unbilled movements (a card export of the open period): checked and stored, never posted to the ledger.
   */
  provisional: boolean;
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
      | "LOW_CONFIDENCE"
      | "SECTION_TOTAL"
      | "INSTALLMENT_SCHEDULE";
    message: string;
    expected: number | null;
    found: number | null;
    on: string | null;
  }[];
  /**
   * Credit card statements only (null on a checking account, and on unbilled exports, which print no amount due).
   */
  obligations: null | Obligations;
}
/**
 * What the card statement says the holder owes. Positive magnitudes in the statement's currency; null when not printed. amount_due is the statement's closing debt, which reconciliation checks.
 */
export interface Obligations {
  amount_due: number | null;
  minimum_due: number | null;
  due_date: string | null;
  credit_limit: number | null;
  credit_used: number | null;
  credit_available: number | null;
  /**
   * Cuotas still to bill after this statement, computed from its cuota lines.
   */
  installments_remaining: number;
  installments: {
    line_index: number;
    description: {
      untrusted_text: string;
    };
    number: number;
    total: number;
    installment_amount: number;
    original_amount: number;
    remaining_amount: number;
  }[];
  /**
   * Cuotas due per later statement month, computed; when the bank prints its own schedule, reconciliation checks these against it (INSTALLMENT_SCHEDULE).
   */
  upcoming: {
    month: string;
    amount: number;
  }[];
}
