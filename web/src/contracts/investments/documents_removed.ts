/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Body of DELETE /v1/investments/documents (ADR-044): the signed-in account forgets every investment document it imported, audited as INVESTMENT_DOCUMENTS_REMOVED with the count only. A demo persona or demo mode gets 403 with the READ_ONLY link outcome. A linked account, if any, stays.
 */
export interface InvestmentDocumentsRemoved {
  removed: number;
}
