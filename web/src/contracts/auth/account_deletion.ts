/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * 200 body of DELETE /v1/account. DELETED: the account, its profile, sessions, statements, transactions, proposals, authorizations and savings rules are gone, the session cookie is cleared, and every session of the account stops working. RESET: a demo persona's statements, transactions, proposals, authorizations and savings rules are gone; the persona and its sessions stay. In both cases the user's audit events became tombstones (kind ERASED) and one ACCOUNT_DELETED or DEMO_DATA_RESET event, with no user id, commits to them. erased counts rows per table.
 */
export interface AccountDeletion {
  status: "DELETED" | "RESET";
  erased: {
    [k: string]: number;
  };
  audit_events_erased: number;
}
