/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * 200 body of GET /v1/me/export (G02, Ley 21.719 arts. 5 and 9), sent as a JSON file download (Content-Disposition: attachment). Everything stored about the signed-in user, from the same stores DELETE /v1/account erases: the account (null for a demo persona), the profile with its questionnaire answers, imported statements, ledger transactions, receipts, connections with their last answers, active savings rules, investments (the link without its access token, the latest snapshot and imported documents) and the user's own audit events, the DATA_EXPORTED event of this export included. Never included: the password hash, session tokens, connection secrets or the investment access token. Sections hold the stored records as they are kept (ids, ISO 8601 times, money as integers in minor units); merchant, issuer and connection text is untrusted data. The format string changes whenever a section is added, renamed or changes shape. HTTP only: no agent tool reads it.
 */
export interface DataExport {
  format: "neural-ledger-export-1";
  exported_at: string;
  user_id: string;
  account: null | {
    email: string;
    created_at: string;
    sample_data: boolean;
  };
  profile: {} | null;
  statements: {}[];
  transactions: {}[];
  receipts: {}[];
  connections: {
    results: {}[];
  }[];
  savings_rules: {}[];
  investments: {
    link: {} | null;
    latest_snapshot: {} | null;
    documents: {}[];
  };
  audit_events: {}[];
}
