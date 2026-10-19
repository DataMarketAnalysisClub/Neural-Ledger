/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of POST /v1/connections/bank/start (ADR-047): what the bank aggregator's widget needs. widget_token is single-use; null in fixture mode, where POST /v1/connections/bank connects the synthetic bank with any exchange token.
 */
export interface BankStart {
  aggregator: string;
  public_key: string | null;
  widget_token: string | null;
}
