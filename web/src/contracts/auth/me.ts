/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * GET /v1/me in accounts mode. data_source is empty for a new account, persona for a demo session, and sample only when the later sample-data feature is enabled. Fetch GET /v1/profile for the wrapped display name; never expose email or a token here.
 */
export interface AuthenticatedUser {
  user_id: string;
  data_source: "empty" | "sample" | "persona";
  expires_at: string;
}
