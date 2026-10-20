/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Body of POST /v1/connections: add an MCP server (ADR-047). The address must be https and resolve only to public addresses. The token, if any, is sent as a Bearer header to that server only, stored sealed and never returned. consent records that the user agrees to read this service's data into Neural Ledger.
 */
export interface ConnectionCreate {
  name: string;
  url: string;
  token?: string | null;
  consent: true;
}
