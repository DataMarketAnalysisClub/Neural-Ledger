/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of GET /v1/statements/{id}: one imported bank statement with its lines. Descriptions are untrusted third-party text, with personal data replaced at import by placeholders (ADR-028). Money is integer minor units of `currency` (CLP: pesos; USD: cents); signs are the holder's: charges negative, money in positive, and a credit card's debt (opening and closing balance) negative.
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
    /**
     * What the bank says the line is, when its layout says it (credit cards). null: the sign decides.
     */
    kind: "purchase" | "payment" | "refund" | "fee" | null;
    /**
     * The printed subtotal the line belongs to (e.g. B, D, E on a card statement).
     */
    section: string | null;
    installment: {
      number: number;
      total: number;
      original_amount: number | null;
      monthly_rate: number | null;
      purchased_on: string | null;
    } | null;
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
   * Masked at import: only the last 4 digits (or the 4 characters a bank already left visible) are kept, e.g. ****3456 (ADR-028).
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
