/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Body of POST /v1/expenses/{proposal_id}/confirm (ADR-038): the user confirms the expense the copilot prepared, completing what it could not tell. The amount is the proposal's and cannot be changed here. The answer is the stored expense, shaped like a receipt (outputs/document_ingest.schema.json#/$defs/receipt, source manual).
 */
export interface ExpenseConfirmation {
  session_id?: string;
  payment: "cash" | "card";
  category?: "groceries" | "dining" | "health" | "shopping" | "transport" | "utilities" | "entertainment" | "other";
  spent_on?: string;
}
