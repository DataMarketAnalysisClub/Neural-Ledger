/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * User-only POST /v1/investments/link (ADR-044), accounts mode and real accounts only (a demo persona or demo mode is 403 READ_ONLY). The email and password are the user's Fintual credentials: the backend sends them once to the provider for an access token and keeps only that token, sealed, with the email. The password is never stored, logged, audited or echoed, and no error repeats a supplied value. consent must be true: the user accepted the text that says what is read and kept (recorded as consent=inv-consent-1 on the INVESTMENTS_LINKED audit event). Linking again replaces the previous link. Not an agent tool: an agent attempt is T3 CREDENTIAL_CHANGE. Rate limited like sign-in.
 */
export interface InvestmentLinkRequest {
  provider?: "fintual";
  email: string;
  password: string;
  consent: true;
}
