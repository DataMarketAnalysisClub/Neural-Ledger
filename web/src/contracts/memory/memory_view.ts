/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Warning codes about declared income (ADR-040). Each one says whether memory is applied or only saved; x-numeric-effect records which. The financial tools that use memory carry them as envelope warnings and the verifier makes the copilot mention them. INCOME_RAISE_ASSUMED: the typical scenario uses a declared amount the statements do not support yet; the conservative one keeps the supported level. SALARY_DIFFERS: the matched credits' median is below the declared amount and the lower is used. SALARY_CONFLICT: two consecutive eligible paydays without a matching credit; memory has no effect until the user confirms a new version. SALARY_UNIDENTIFIED: the salary could not be identified in every cycle of the estimation window, or there is no verified base; memory is saved with no effect.
 */
export type MemoryWarningCode = "INCOME_RAISE_ASSUMED" | "SALARY_DIFFERS" | "SALARY_CONFLICT" | "SALARY_UNIDENTIFIED";

/**
 * data of GET /v1/memory (Perfil, "Lo que Neural Ledger sabe de ti") and of the confirmation and Perfil writes (ADR-047): per chain, the version that applies today, the next one if it starts later, and what the statements say about it. Without the memory consent, `items` still lists the declarations so the user can delete them, but `check` is null and nothing is applied. A shared persona has no items.
 */
export interface MemoryView {
  catalog_version: "mem-0.1";
  consent: "granted" | "missing" | "revoked";
  items: Item[];
}
export interface Item {
  chain_id: string;
  type: "salary_net";
  /**
   * How many versions the chain holds; the export lists them all.
   */
  versions: number;
  /**
   * The version that applies to the pay month of today; null when every version starts later.
   */
  current: MemoryDeclaration | null;
  /**
   * The next version, when it starts after the pay month of today.
   */
  upcoming: MemoryDeclaration | null;
  check: SalaryCheck | null;
}
/**
 * One stored version of a memory chain, as GET /v1/memory and the export show it (ADR-047). Only the user confirms a declaration; whether evidence supports it is derived on read (salary_check), never stored. The origin is an opaque reference: memory keeps neither the message nor its hash. The owner comes from authentication and is not part of the view.
 */
export interface MemoryDeclaration {
  memory_id: string;
  chain_id: string;
  /**
   * 1 for the first declaration of the chain; each edit or re-confirmation appends the next.
   */
  version: number;
  catalog_version: "mem-0.1";
  value: MemoryValue;
  confirmed_at: string;
  confirmed_by: "user";
  source: "chat" | "profile";
  origin:
    | {
        kind: "chat";
        session_id: string;
        message_id: string;
      }
    | {
        kind: "profile";
      }
    | {
        kind: "statement";
        statement_id: string;
        txn_id: string;
      };
  /**
   * The audit event that recorded the confirmation.
   */
  audit_ref: string;
}
/**
 * A typed value of the closed memory catalog mem-0.1 (ADR-047). One type today: salary_net, the user's declared net salary from a pay month on. Unknown types and fields are refused; a boolean is not an amount. A value is what the user declared, never a credited salary.
 */
export interface MemoryValue {
  type: "salary_net";
  salary_net: SalaryNet;
}
export interface SalaryNet {
  /**
   * CLP, net of deductions (líquido).
   */
  amount: number;
  net: true;
  /**
   * YYYY-MM: the month whose payday (last weekday) first credits the salary. It funds the next pay cycle (ADR-040).
   */
  effective_from: string;
}
/**
 * What the statements say about a salary_net chain, derived on every read from the declarations, the eligible credits, statement coverage and fc-0.4 (ADR-040). Nothing here is stored. Evidence is tied to the expected payday of each pay month, not to the credit's calendar month. `numeric_effect` says whether the forecast uses the declaration (applied) or only keeps it for checking (saved_only); a declaration is never a credited salary.
 */
export interface SalaryCheck {
  /**
   * declared: no match and no conflict. verified: at least one match. conflict: two consecutive eligible paydays without a match; it lasts until the user confirms a new version.
   */
  status: "declared" | "verified" | "conflict";
  /**
   * Matches of the current version, counted from its effective_from.
   */
  matched: number;
  /**
   * Eligible paydays without a match, counted from max(payday(effective_from), confirmed_at).
   */
  missed: number;
  evidence: Payday[];
  numeric_effect: "applied" | "saved_only";
  /**
   * Why the effect is what it is; each code is also a warning of the financial tools that use memory.
   */
  reasons: MemoryWarningCode[];
  params_version: string;
}
export interface Payday {
  /**
   * YYYY-MM: the month whose payday (last weekday) first credits the salary. It funds the next pay cycle (ADR-040).
   */
  pay_month: string;
  expected_payday: string;
  /**
   * The chain version that applies to this pay month.
   */
  version: number;
  /**
   * not_eligible: the window payday ± 3 business days is not fully covered by verified, final statements, or has not ended; never a non-compliance, and it breaks consecutiveness. before_confirmation: no match, but the payday is before the version was confirmed, so it is not counted as missed.
   */
  outcome: "matched" | "missed" | "not_eligible" | "before_confirmation";
  credit?: Credit;
}
export interface Credit {
  statement_id: string;
  txn_id: string;
  amount: number;
  posted_on: string;
}
