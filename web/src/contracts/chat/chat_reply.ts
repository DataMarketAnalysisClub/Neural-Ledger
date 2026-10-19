/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Reply to a chat turn. When pending_proposal is present, the UI shows a confirmation card with exactly its terms; confirming calls POST /v1/actions/proposals/{proposal_id}/confirm.
 */
export interface ChatReply {
  session_id: string;
  text: string;
  intent:
    | "afford_purchase"
    | "forecast"
    | "protected_surplus"
    | "savings_plan"
    | "set_liquidity_floor"
    | "execute_action"
    | "explain"
    | "out_of_scope"
    | "smalltalk";
  intent_confidence: number;
  gate: "proceed" | "clarify" | "read_only";
  decision_model?: string | null;
  language_model?: string | null;
  tools_called: string[];
  facts: Fact[];
  warnings: Caveat[];
  verification?: {
    ok?: boolean;
    issues?: {
      kind?: string;
      detail?: string;
    }[];
    numbers_checked?: number;
  } | null;
  /**
   * True when the text is the deterministic narration (offline mode, or the model's explanation failed verification).
   */
  fallback_used: boolean;
  pending_proposal?: {} | null;
  actions: ActionOutcome[];
  blocked_reason?: string | null;
}
export interface Fact {
  key: string;
  value: number | string;
  /**
   * ISO currency code for money, '%', 'month', 'count', 'ratio', 'profile', ...
   */
  unit: string;
  derivation: string;
}
export interface Caveat {
  code: string;
  message: string;
  /**
   * The explanation passes if it contains any of these tokens.
   */
  must_mention: string[];
}
/**
 * Result of propose / confirm / execute. BLOCKED always carries a reason and is always audited.
 */
export interface ActionOutcome {
  status: "PROPOSED" | "CONFIRMED" | "EXECUTED" | "FAILED" | "BLOCKED" | "INVALID_INPUT" | "INSUFFICIENT_DATA";
  proposal?: {
    proposal_id: string;
    session_id: string;
    user_id: string;
    terms: ActionTerms;
    source_snapshot_id: string;
    created_at: string;
    expires_at: string;
    status: "pending" | "confirmed";
  } | null;
  /**
   * Public view: the signature (action_hash) never leaves the server.
   */
  authorization?: {
    authorization_id: string;
    proposal_id: string;
    terms: ActionTerms;
    expires_at: string;
    used: boolean;
  } | null;
  receipt?: {
    execution_id?: string;
    ok?: boolean;
    reference?: string | null;
    error?: string | null;
  } | null;
  reason?:
    | null
    | "UNKNOWN_TOOL"
    | "NEW_BENEFICIARY"
    | "UNKNOWN_DESTINATION"
    | "LIMIT_CHANGE"
    | "CREDENTIAL_CHANGE"
    | "POLICY_OVERRIDE"
    | "SELF_ESCALATION"
    | "TIER_NOT_ALLOWED"
    | "INJECTION_SUSPECTED"
    | "LOW_CONFIDENCE"
    | "AUTHORIZATION_NOT_FOUND"
    | "AUTHORIZATION_EXPIRED"
    | "AUTHORIZATION_REPLAYED"
    | "AUTHORIZATION_TAMPERED"
    | "AUTHORIZATION_MISMATCH"
    | "WRONG_OWNER"
    | "ACTION_NOT_ALLOWED"
    | "UNKNOWN_SOURCE"
    | "AMOUNT_OVER_LIMIT"
    | "PROPOSAL_NOT_FOUND"
    | "PROPOSAL_EXPIRED"
    | "PROPOSAL_NOT_PENDING"
    | "TERMS_CHANGED"
    | "AUDIT_UNAVAILABLE";
  detail?: string | null;
  field?: string | null;
  authorized_amount?: number | null;
  requested_amount?: number | null;
}
/**
 * The confirmation contract (Spec v0 section 5). The UI shows exactly these terms and execution must match them exactly. The amount comes from a stored plan snapshot (create_savings_rule) or from the user's own message (set_liquidity_floor, ADR-037), never from model text. A set_liquidity_floor moves no money: source and destination are both the account it protects (checking).
 */
export interface ActionTerms {
  action: "create_savings_rule" | "set_liquidity_floor";
  amount: number;
  currency: string;
  frequency: "monthly";
  source_account: string;
  destination: string;
  effective_date: string;
}
