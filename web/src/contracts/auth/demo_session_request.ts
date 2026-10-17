/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * POST /v1/auth/demo-session in accounts mode when NL_DEMO_PERSONAS is enabled. Public, shared, read-only persona records; no arbitrary user ID is accepted.
 */
export interface DemoSessionRequest {
  persona: "camila" | "diego";
}
