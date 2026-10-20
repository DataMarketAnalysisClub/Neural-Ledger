/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * POST /v1/auth/signup. Email is normalized and checked by the domain, then its domain by the configured checks (NL_EMAIL_CHECKS): a disposable inbox, or a domain that does not exist or receives no mail, is INVALID_INPUT on email; the password is never returned. The display name follows the domain's Unicode-letter rule: 1-40 code points of letters, spaces, periods, apostrophes or hyphens only, with no controls or newlines. Language defaults to en. sandbox_acknowledged must be true: the user ticked the sandbox notice (a hackathon sandbox; no real bank statements or personal data). The server refuses the request otherwise and records the notice version on USER_REGISTERED.
 */
export interface SignupRequest {
  email: string;
  password: string;
  display_name: string;
  language?: string;
  sandbox_acknowledged: true;
}
