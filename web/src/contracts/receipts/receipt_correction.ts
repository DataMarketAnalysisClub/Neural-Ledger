/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Body of PATCH /v1/receipts/{receipt_id} (ADR-039): the total or the date of a receipt as the user typed it, when the reader could not read it or read it with doubt. Sent by the app's form only: the copilot asks for the value but no agent tool corrects a receipt. The answer is the receipt as it now stands (outputs/document_ingest.schema.json#/$defs/receipt).
 */
export type ReceiptCorrection = {
  [k: string]: unknown;
} & {
  session_id?: string;
  /**
   * CLP, whole pesos.
   */
  total?: number;
  /**
   * From 2000-01-01 to today.
   */
  issued_on?: string;
};
