/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Read this user's audit events in this session (decisions, tool calls, confirmations, executions and blocked attempts) and whether the hash chain is intact. Use it when the user asks why something was blocked.
 */
export interface GetAuditEventsInput {
  limit?: number;
}
