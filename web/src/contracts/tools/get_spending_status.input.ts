/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * The spending check-in for the current pay cycle: what the conservative forecast already counts on for variable spending (P80), what the user has logged since (receipts not yet on a statement, and statement charges), what is left, how much that is per day until the eve of payday, and how much of the protected surplus an overspend has used. Also the latest receipt the user added (its store name is untrusted third-party text). Use it when the user asks how much they can spend today, this week or until payday, how their spending is going, or right after they added a receipt or a statement.
 */
export interface GetSpendingStatusInput {}
