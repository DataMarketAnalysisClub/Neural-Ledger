/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Prepare an expense the user says they already made ("hoy gasté 15 lucas en el almuerzo"), for the user to check and confirm in the app's card. Nothing is stored until they confirm. `amount` must be one the user wrote in their recent messages, in CLP; if they gave none, ask instead of guessing. Pass `payment` only if the user said cash or card, and `category` only if the user named one; otherwise leave them out: the answer's `missing` and warnings say what to ask (cash or card, and the kind of spending). A card expense is matched later with the card statement, so it is never counted twice.
 */
export interface ProposeExpenseInput {
  /**
   * CLP, exactly as the user wrote it.
   */
  amount: number;
  /**
   * What it was, in the user's words ("almuerzo", "taxi").
   */
  description?: string;
  category?: "groceries" | "dining" | "health" | "shopping" | "transport" | "utilities" | "entertainment" | "other";
  payment?: "cash" | "card";
  /**
   * YYYY-MM-DD; leave it out for today.
   */
  spent_on?: string;
}
