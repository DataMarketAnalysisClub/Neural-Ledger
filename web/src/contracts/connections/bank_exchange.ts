/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Body of POST /v1/connections/bank: connect the user's bank (ADR-047). exchange_token is what the aggregator's widget returned; the server trades it for a read-only link it stores sealed. In fixture mode any non-empty token connects the synthetic bank.
 */
export interface BankExchange {
  exchange_token: string;
  consent: true;
}
