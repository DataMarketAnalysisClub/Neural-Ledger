/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Error body of the memory HTTP routes (GET and DELETE /v1/memory, the proposal confirmation, PUT /v1/profile/income). Messages are generic and never echo a supplied amount. The x-http-status annotation maps status codes to HTTP responses; it is not a body field.
 */
export interface MemoryError {
  /**
   * NOT_FOUND also covers another user's chain or proposal. PROPOSAL_USED: already confirmed (single use). PROPOSAL_STALE: the chain changed or was deleted after the proposal, or consent was revoked. CONSENT_REQUIRED: the memory consent is missing or revoked.
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
