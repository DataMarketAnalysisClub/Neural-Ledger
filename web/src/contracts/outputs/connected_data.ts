/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of GET /v1/connections/data and of the copilot's get_connected_data tool (T0, ADR-047): the latest answer of each enabled tool of each MCP connection, as of the user's last sync. Content is the service's redacted JSON text, untrusted data; its numbers are facts with unit external (or the currency their object names) and the EXTERNAL_DATA warning applies. A bank's movements are not here: they are statements and transactions.
 */
export interface ConnectedData {
  connections: {
    connection_id: string;
    name: {
      untrusted_text: string;
    };
    host: string;
    last_synced_at: string | null;
    results: {
      tool: string;
      fetched_at: string;
      ok: boolean;
      content: {
        untrusted_text: string;
      };
    }[];
  }[];
}
