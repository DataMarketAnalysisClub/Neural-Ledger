/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Spec v0 section 10 fields plus a hash chain (sequence, prev_hash, event_hash). event_hash = sha256 of the canonical JSON of every other field. No hidden model reasoning is ever logged. A tombstone (kind ERASED, after an account deletion or a demo reset) keeps sequence, prev_hash and event_hash of the erased event and nothing else about it; its detail is erased_by=<event_id> of the later ACCOUNT_DELETED or DEMO_DATA_RESET event, whose detail commits to the erased sequences (erased_events, erased_sha256).
 */
export interface AuditEvent {
  event_id: string;
  sequence: number;
  timestamp: string;
  session_id: string;
  /**
   * Owner of the event. Audit reads are scoped to it; null for system-wide events.
   */
  user_id?: string | null;
  actor: "user" | "agent" | "system";
  kind:
    | "DECISION"
    | "TOOL_CALL"
    | "CLARIFICATION_REQUESTED"
    | "INJECTION_FLAGGED"
    | "OUT_OF_SCOPE"
    | "VERIFICATION_FAILED"
    | "PROPOSAL_CREATED"
    | "ACTION_CONFIRMED"
    | "EXECUTION_STARTED"
    | "ACTION_EXECUTED"
    | "ACTION_FAILED"
    | "ACTION_BLOCKED"
    | "STATEMENT_IMPORTED"
    | "DOCUMENT_ROUTED"
    | "RECEIPT_IMPORTED"
    | "EXPENSE_LOGGED"
    | "RECEIPT_CORRECTED"
    | "CONNECTION_ADDED"
    | "CONNECTION_UPDATED"
    | "CONNECTION_SYNCED"
    | "CONNECTION_REMOVED"
    | "CATEGORY_CHANGED"
    | "PROFILE_UPDATED"
    | "DATA_EXPORTED"
    | "USER_REGISTERED"
    | "SESSION_STARTED"
    | "SESSION_ENDED"
    | "ACCOUNT_DELETED"
    | "DEMO_DATA_RESET"
    | "MEMORY_CONSENT_CHANGED"
    | "MEMORY_CONFIRMED"
    | "MEMORY_DELETED"
    | "MEMORY_EVIDENCE_CHANGED"
    | "ERASED"
    | "INVESTMENTS_LINKED"
    | "INVESTMENTS_SYNCED"
    | "INVESTMENTS_UNLINKED"
    | "INVESTMENT_DOCUMENT_IMPORTED"
    | "INVESTMENT_DOCUMENTS_REMOVED";
  user_intent?: string | null;
  intent_confidence?: number | null;
  tool_requested?: string | null;
  tool_parameters_hash?: string | null;
  forecast_snapshot_id?: string | null;
  policy_version?: string | null;
  decision_model_checks?: {
    model: string;
    key: string;
    label: string;
    confidence: number;
  }[];
  permission_tier?: null | "T0" | "T1" | "T2" | "T3";
  authorization_id?: string | null;
  execution_result?: string | null;
  blocked_reason?: string | null;
  model_version?: string | null;
  detail?: string | null;
  prev_hash: string;
  event_hash: string;
}
