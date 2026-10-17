/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * POST /v1/auth/signup. Email is normalized and checked by the domain; the password is never returned. The display name follows the domain's Unicode-letter rule: 1-40 code points of letters, spaces, periods, apostrophes or hyphens only, with no controls or newlines. Language defaults to en.
 */
export interface SignupRequest {
  email: string;
  password: string;
  display_name: string;
  language?: string;
}
