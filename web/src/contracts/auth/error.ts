/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Error body for auth, identity and profile-write HTTP routes. Messages are generic and must never echo a supplied email, password or session token. INVALID_CREDENTIALS is identical for absent accounts, malformed email and wrong passwords. The x-http-status annotation maps status codes to HTTP responses; it is not a JSON body field.
 */
export interface AuthError {
  status:
    | "IDENTITY_HEADER_REJECTED"
    | "UNAUTHENTICATED"
    | "INVALID_CREDENTIALS"
    | "ORIGIN_REJECTED"
    | "PROFILE_READ_ONLY"
    | "NOT_FOUND"
    | "EMAIL_TAKEN"
    | "INVALID_INPUT";
  message: string;
  field?: string;
}
