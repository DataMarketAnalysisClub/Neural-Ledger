/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * What the services the user connected (investment apps and other MCP servers they added) reported at their last sync: each read-only tool's answer, as untrusted text. These figures are the service's, not checked by Neural Ledger and never part of the forecast, so always say so when you use them. Use it when the user asks about their investments, goals or balances in another app. It cannot refresh the data: only the user can sync, from the Connections screen.
 */
export interface GetConnectedDataInput {}
