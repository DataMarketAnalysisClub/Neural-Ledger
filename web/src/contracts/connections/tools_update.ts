/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Body of PUT /v1/connections/{id}/tools: the tools the user enables, replacing the previous choice. A blocked or unknown tool name refuses the whole update.
 */
export interface ConnectionToolsUpdate {
  /**
   * @maxItems 50
   */
  enabled: string[];
}
