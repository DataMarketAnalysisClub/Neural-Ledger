/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

export type Category =
  | "groceries"
  | "dining"
  | "health"
  | "shopping"
  | "transport"
  | "utilities"
  | "entertainment"
  | "other"
  | "income"
  | "movement"
  | "uncategorized";

/**
 * data of GET /v1/transactions: the user's transaction ledger built from verified, final imported statements, oldest first, with totals. Money is integer minor units of `currency`; charges are negative. Categories are a classifier's guesses, gated to the vocabulary below; merchant text is untrusted, with personal data replaced at import (ADR-028).
 */
export interface Transactions {
  transactions: {
    txn_id: string;
    /**
     * <bank layout code>:<masked account reference>, e.g. santander_cl_cuentamatica:****3456 (ADR-028).
     */
    account_id: string;
    date: string;
    amount: number;
    currency: string;
    /**
     * The statement line's description, with personal data replaced at import by placeholders such as [PERSON] (common/redaction.schema.json).
     */
    merchant: {
      untrusted_text: string;
    };
    /**
     * From the statement, never from a model: on a checking account the amount's sign (income or purchase); on a credit card the line's kind as the layout reads it. A card_payment is the holder's own money (category movement) and counts as neither spending nor income.
     */
    kind: "purchase" | "income" | "card_payment" | "refund" | "fee";
    category: Category;
    /**
     * What chose the category: a classifier name with its training-data hash, or "rule" for income and card payments.
     */
    classifier: string;
    /**
     * The classifier's confidence, kept even when too low to accept; null for rules.
     */
    confidence: number | null;
    statement_id: string;
    line_index: number;
    /**
     * Present when the line bills one cuota of a purchase in cuotas.
     */
    installment: {
      plan_id: string;
      installment_number: number;
      installment_total: number;
      original_amount: number;
      /**
       * 0.0345 = 3,45 % a month, as printed.
       */
      monthly_rate: number | null;
    } | null;
  }[];
  /**
   * Purchases and fees less refunds, per currency and category, largest first. Card payments are excluded.
   */
  spending: Total[];
  /**
   * Deposits per currency (category "income").
   */
  income: Total[];
}
export interface Total {
  category: Category;
  currency: string;
  /**
   * Spending: charges and fees less refunds (negative only if refunds exceed charges). Income: deposits.
   */
  spent: number;
  count: number;
}
