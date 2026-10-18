/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * User-only PATCH /v1/transactions/{txn_id} request (ADR-023, G04). The user sets the category of one of their transactions; it is stored with classifier "user", wins over any model, survives re-imports and is audited as CATEGORY_CHANGED. The kind and the amount never change, so the categories a transaction can take depend on its kind: a purchase, fee or refund takes a spending category or movement; an income takes income or movement; a card_payment takes only movement. Any other value is INVALID_INPUT (422) listing the allowed ones in common/envelope; a transaction that is not the caller's, or does not exist, is 404 with an INSUFFICIENT_DATA envelope (missing ["transaction"]), the same for both. The response's data is one transaction as in outputs/transactions. Not an agent tool.
 */
export interface CategoryUpdate {
  category:
    | "groceries"
    | "dining"
    | "health"
    | "shopping"
    | "transport"
    | "utilities"
    | "entertainment"
    | "other"
    | "income"
    | "movement";
  /**
   * Recorded on the audit event; defaults to "default".
   */
  session_id?: string;
}
