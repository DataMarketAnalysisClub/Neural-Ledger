/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of get_commitments. Labels are untrusted third-party text.
 */
export interface Commitments {
  horizon_months: number;
  commitments: {
    commitment_id: string;
    type: "installment" | "rent" | "subscription" | "loan";
    label: {
      untrusted_text: string;
    };
    amount: number;
    first_due: string;
    last_due: string | null;
    is_debt: boolean;
  }[];
  schedule: {
    month: string;
    total: number;
    debt: number;
  }[];
}
