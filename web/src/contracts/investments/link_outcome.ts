/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Body of every /v1/investments/link and /v1/investments/sync response (ADR-044). HTTP status by status: LINKED 201 (POST link) or 200 (GET link), SYNCED 200, UNLINKED 200, NOT_LINKED 404, INVALID_INPUT 422 (field names the input; never its value), ACCESS_REJECTED 422 (the provider refused the email and password), READ_REFUSED 502 (the provider accepted the sign-in but refused to share the goals with that token; nothing is stored), RELINK_REQUIRED 409 (the provider no longer accepts the stored link: link again), CONFLICT 409 (the link changed during the request), PROVIDER_UNAVAILABLE 503, READ_ONLY 403 (demo mode or a demo persona). link never carries the token, and the email only masked (first character and domain). A malformed body (not JSON, unknown or missing fields, a field of the wrong type) answers the AuthError of auth/error.schema.json, 422 with its field, like the other user-only writes.
 */
export interface InvestmentLinkOutcome {
  status:
    | "LINKED"
    | "SYNCED"
    | "UNLINKED"
    | "NOT_LINKED"
    | "INVALID_INPUT"
    | "ACCESS_REJECTED"
    | "READ_REFUSED"
    | "RELINK_REQUIRED"
    | "CONFLICT"
    | "PROVIDER_UNAVAILABLE"
    | "READ_ONLY";
  link: null | Link;
  field?: string | null;
  message?: string | null;
}
export interface Link {
  provider: "fintual";
  /**
   * Masked: the first character of the address and its domain.
   */
  email: string;
  linked_at: string;
  synced_at: string | null;
  goals: number | null;
  synthetic: boolean;
  relink_required: boolean;
}
