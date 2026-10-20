/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * A read-only connection the user added (ADR-047): an MCP server they chose, or their bank through an aggregator. Only the server's host is shown, never the full address or the token. Tool names and descriptions are the server's text: untrusted data.
 */
export interface Connection {
  connection_id: string;
  kind: "mcp" | "bank";
  /**
   * The user's label.
   */
  name: string;
  /**
   * The MCP server's host, or the aggregator's name for a bank.
   */
  host: string;
  created_at: string;
  last_synced_at: string | null;
  /**
   * @maxItems 50
   */
  tools: Tool[];
}
export interface Tool {
  name: string;
  description: {
    untrusted_text: string;
  };
  /**
   * What the server declares; never trusted alone.
   */
  read_only_hint: boolean | null;
  destructive_hint: boolean | null;
  /**
   * Why this tool can never be enabled; null if the user may enable it.
   */
  blocked: ("NOT_READ_ONLY" | "DESTRUCTIVE" | "WRITE_VERB" | "NEEDS_ARGUMENTS") | null;
  enabled: boolean;
}
