/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * POST /v1/chat. The user is identified by the X-User-Id header (sandbox only).
 */
export interface ChatRequest {
  session_id?: string;
  message: string;
}
