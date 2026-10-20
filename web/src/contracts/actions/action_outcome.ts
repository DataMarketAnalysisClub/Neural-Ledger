/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

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
    | "PLAN_SUPERSEDED"
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
