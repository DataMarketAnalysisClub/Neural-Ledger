/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * POST /v1/auth/signin. Both fields are strings without signup length constraints. Unknown or malformed email and wrong password must receive the same generic INVALID_CREDENTIALS response and password-check work; neither value appears in the response.
 */
export interface SigninRequest {
  email: string;
  password: string;
}
