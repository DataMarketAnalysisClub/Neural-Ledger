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
    | "spending_check"
    | "log_expense"
    | "report_income_change"
    | "savings_plan"
    | "set_liquidity_floor"
    | "execute_action"
    | "explain"
    | "investments"
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
  /**
   * An expense the copilot prepared from what the user said (ADR-039). The UI shows it for the user to check, complete (cash or card, category) and confirm; confirming calls POST /v1/expenses/{proposal_id}/confirm. Nothing is stored before.
   */
  pending_expense?: ExpenseProposal | null;
  /**
   * A net salary the copilot read from this message (ADR-048). The UI shows the memory card for the user to select or type the amount, check the pay month and confirm with POST /v1/memory/proposals/{proposal_id}/confirm. Nothing is saved before; confirming moves no money and does not change the projections.
   */
  pending_memory_proposal?: IncomeProposal | null;
  /**
   * Present when the reply relied on the user's memory: the counters it read (memory_consent), current when the reply was published. The counters only grow: once a client has seen either one larger (from GET or PUT /v1/memory/consent or another reply), the whole reply is obsolete and the client hides it: text, facts, cards and actions. A reply whose memory moved during its turn is never published: it comes back as MEMORY_CHANGED, without this field.
   */
  memory_dependency?: {
    consent_generation: number;
    memory_revision: number;
  } | null;
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
 * data of the propose_expense tool and pending_expense of a chat reply (ADR-039): an expense prepared from what the user said, waiting for their confirmation. `missing` lists what the copilot asks and the card collects.
 */
export interface ExpenseProposal {
  proposal_id: string;
  amount: number;
  currency: "CLP";
  description: {
    untrusted_text: string;
  };
  spent_on: string;
  category: string;
  payment: "cash" | "card" | "unknown";
  missing: ("payment" | "category")[];
}
/**
 * data of the propose_income_change tool (ADR-048): a salary declaration prepared from the message that started the turn, never from earlier messages, for the user to complete and confirm in the card. Nothing is stored until they confirm (POST /v1/memory/proposals/{proposal_id}/confirm), once. READY: one amount, prefilled. CHOOSE_AMOUNT: several, the user picks; the model never decides which is the old and which the new salary. ASK_AMOUNT: none, the card asks; no amount is invented. The interpreted pay month is always shown. `needs_base` asks for the previous salary and its pay month when the chain has no version yet.
 */
export interface IncomeProposal {
  proposal_id: string;
  status: "READY" | "CHOOSE_AMOUNT" | "ASK_AMOUNT";
  /**
   * Amounts read from the current message, in the order written, without repeats.
   */
  candidates: number[];
  effective_from: {
    /**
     * YYYY-MM: the month whose payday (last weekday) first credits the salary. It funds the next pay cycle (ADR-049).
     */
    pay_month: string;
    /**
     * explicit_year: month and year written. next_occurrence: a month without a year, read as its next occurrence, the current month included (never retroactive). next_payday: no month written; the next payday's month.
     */
    read_as: "explicit_year" | "next_occurrence" | "next_payday";
  };
  needs_base: boolean;
  /**
   * The salary chain this proposal extends; null for the first declaration.
   */
  chain_id: string | null;
  /**
   * The chain's latest version when the proposal was made (0 for none). Confirming fails with PROPOSAL_STALE if it changed.
   */
  expected_version: number;
  currency: "CLP";
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
