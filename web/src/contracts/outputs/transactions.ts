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
  | "savings"
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
     * What chose the category: a classifier name with its training-data hash, "rule" for income and card payments, or "user" when the user set it (PATCH /v1/transactions/{txn_id}, ADR-023).
     */
    classifier: string;
    /**
     * The classifier's confidence, kept even when too low to accept; null for rules and for the user.
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
   * Purchases and fees less refunds, per currency and category, largest first. The holder's own money is excluded: Movimientos (card payments, and anything the user marks movement) and Ahorro (savings lines, ADR-036).
   */
  spending: Total[];
  /**
   * Deposits per currency (category "income"), without the holder's own money (movement, savings).
   */
  income: Total[];
  /**
   * Money set aside in the holder's savings or investment products less money back from them, per currency (category "savings", ADR-036). Neither spending nor income. Set by a layout rule or by the user, never by a model.
   */
  savings: Total[];
}
export interface Total {
  category: Category;
  currency: string;
  /**
   * Spending: charges and fees less refunds (negative only if refunds exceed charges). Income: deposits. Savings: set aside less withdrawn (negative if more came back than went in).
   */
  spent: number;
  count: number;
}
