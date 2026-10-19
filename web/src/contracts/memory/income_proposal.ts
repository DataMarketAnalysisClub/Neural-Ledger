/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of the propose_income_change tool (ADR-047): a salary declaration prepared from the message that started the turn, never from earlier messages, for the user to complete and confirm in the card. Nothing is stored until they confirm (POST /v1/memory/proposals/{proposal_id}/confirm), once. READY: one amount, prefilled. CHOOSE_AMOUNT: several, the user picks; the model never decides which is the old and which the new salary. ASK_AMOUNT: none, the card asks; no amount is invented. The interpreted pay month is always shown. `needs_base` asks for the previous salary and its pay month when the chain has no version yet.
 */
export interface IncomeProposal {
  proposal_id: string;
  status: "READY" | "CHOOSE_AMOUNT" | "ASK_AMOUNT";
  /**
   * Amounts read from the current message, in the order written, without repeats.
   */
  candidates: number[];
  effective_from: {
    /**
     * YYYY-MM: the month whose payday (last weekday) first credits the salary. It funds the next pay cycle (ADR-040).
     */
    pay_month: string;
    /**
     * explicit_year: month and year written. next_occurrence: a month without a year, read as its next occurrence, the current month included (never retroactive). next_payday: no month written; the next payday's month.
     */
    read_as: "explicit_year" | "next_occurrence" | "next_payday";
  };
  needs_base: boolean;
  /**
   * The salary chain this proposal extends; null for the first declaration.
   */
  chain_id: string | null;
  /**
   * The chain's latest version when the proposal was made (0 for none). Confirming fails with PROPOSAL_STALE if it changed.
   */
  expected_version: number;
  currency: "CLP";
}
