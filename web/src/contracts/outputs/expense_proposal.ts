/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of the propose_expense tool and pending_expense of a chat reply (ADR-039): an expense prepared from what the user said, waiting for their confirmation. `missing` lists what the copilot asks and the card collects.
 */
export interface ExpenseProposal {
  proposal_id: string;
  amount: number;
  currency: "CLP";
  description: {
    untrusted_text: string;
  };
  spent_on: string;
  category: string;
  payment: "cash" | "card" | "unknown";
  missing: ("payment" | "category")[];
}
