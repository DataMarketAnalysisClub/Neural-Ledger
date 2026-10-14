/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of GET /v1/statements/{id}: one imported bank statement with its lines. Descriptions are untrusted third-party text, with personal data replaced at import by placeholders (ADR-028). Money is integer minor units of `currency`; charges are negative.
 */
export interface Statement {
  statement: Summary;
  lines: {
    index: number;
    posted_on: string;
    /**
     * The line's text as the bank printed it, except personal data, replaced at import by placeholders such as [PERSON] (common/redaction.schema.json).
     */
    description: {
      untrusted_text: string;
    };
    amount: number;
    reference: string | null;
    branch: string | null;
    /**
     * Lowest OCR confidence over the line's cells; null when read from a text layer.
     */
    confidence: number | null;
  }[];
  daily_balances: {
    on: string;
    balance: number;
  }[];
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
