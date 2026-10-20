/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of GET and PUT /v1/memory/consent (ADR-048 §6): the user's memory consent and the counters that tell a client its cached memory is obsolete. `consent_generation` grows by one on every actual change of `consent` and never on a repeated update. `memory_revision` grows whenever a declaration is confirmed or a chain is deleted, and is never reset, a chain deleted and created again included. A proposal captures both; a change of either makes it PROPOSAL_STALE, and consenting again never revives it. Without consent nothing reads memory for tools or calculations and no proposal is prepared or confirmed; reading, exporting and deleting one's own declarations stay available. `changed` (PUT only) says whether this request changed the consent. The owner comes from authentication.
 */
export interface MemoryConsent {
  consent: "missing" | "granted" | "revoked";
  consent_generation: number;
  memory_revision: number;
  changed?: boolean;
}
