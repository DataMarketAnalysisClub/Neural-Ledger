/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Body of successful signup (201), signin (200) or demo-session (200). The secret session token is set only in the HttpOnly nl_session cookie, never in JSON. Signout returns 204 with no body.
 */
export interface AuthSession {
  user_id: string;
  expires_at: string;
}
