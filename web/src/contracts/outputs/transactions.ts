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
  | "uncategorized";

/**
 * data of GET /v1/transactions: the user's transaction ledger built from verified imported statements, oldest first, with totals. Money is integer minor units of `currency`; charges are negative. Categories are a classifier's guesses, gated to the vocabulary below; merchant text is untrusted, with personal data replaced at import (ADR-028).
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
     * From the amount's sign; never from a model.
     */
    kind: "purchase" | "income";
    category: Category;
    /**
     * What chose the category: a classifier name with its training-data hash, or "rule" for income.
     */
    classifier: string;
    /**
     * The classifier's confidence, kept even when too low to accept; null for rules.
     */
    confidence: number | null;
    statement_id: string;
    line_index: number;
  }[];
  /**
   * Charges per currency and category, largest first.
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
   * Positive magnitude.
   */
  spent: number;
  count: number;
}
