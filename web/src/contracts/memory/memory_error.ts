/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Error body of the memory HTTP routes (GET, PUT and DELETE under /v1/memory, the proposal confirmation, PUT /v1/profile/income). Messages are generic and never echo a supplied amount or reveal another user's resources. After the body is structurally valid, the first failing check wins, in this order: authentication and persona (UNAUTHENTICATED, PERSONA_READ_ONLY); the owned resource (NOT_FOUND, also for another user's); current consent (CONSENT_REQUIRED); a consumed proposal (PROPOSAL_USED); an expired proposal or a change of what it captured (PROPOSAL_STALE); the request's expected_version (VERSION_CONFLICT). The x-http-status annotation maps status codes to HTTP responses; it is not a body field.
 */
export interface MemoryError {
  /**
   * NOT_FOUND also covers another user's chain or proposal. PROPOSAL_USED: already confirmed (single use). PROPOSAL_STALE: the proposal expired (now >= expires_at, PP_0_1.proposal_ttl_seconds after it was prepared; confirming or consenting again never extends it), was invalidated (its chain deleted, consent revoked), or the consent generation, the memory revision or the chain it captured changed. VERSION_CONFLICT: the request's expected_version is not the chain's latest version. CONSENT_REQUIRED: the memory consent is missing or revoked.
   */
  status:
    | "UNAUTHENTICATED"
    | "PERSONA_READ_ONLY"
    | "NOT_FOUND"
    | "PROPOSAL_USED"
    | "PROPOSAL_STALE"
    | "VERSION_CONFLICT"
    | "INVALID_INPUT"
    | "CONSENT_REQUIRED";
  message: string;
  field?: string;
}
