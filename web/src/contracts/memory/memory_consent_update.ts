/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Body of PUT /v1/memory/consent: grant or revoke the memory consent. User-only HTTP flow; the owner comes from authentication, never from the body. Repeating the current value changes nothing (changed: false) and writes no audit event. Revoking keeps the declarations, stops their use and invalidates pending proposals; revoking a consent never granted leaves it missing. The answer is memory_consent.
 */
export interface MemoryConsentUpdate {
  consent: "granted" | "revoked";
}
