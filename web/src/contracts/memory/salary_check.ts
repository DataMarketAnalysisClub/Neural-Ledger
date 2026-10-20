/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Warning codes about declared income (ADR-049). Each one says whether memory is applied or only saved; x-numeric-effect records which. The financial tools that use memory carry them as envelope warnings and the verifier makes the copilot mention them. INCOME_RAISE_ASSUMED: the typical scenario uses a declared amount the statements do not support yet; the conservative one keeps the supported level. SALARY_DIFFERS: the matched credits' median is below the declared amount and the lower is used. SALARY_CONFLICT: two consecutive eligible paydays without a matching credit; memory has no effect until the user confirms a new version. SALARY_UNIDENTIFIED: the salary could not be identified in every cycle of the estimation window, or there is no verified base; memory is saved with no effect.
 */
export type MemoryWarningCode = "INCOME_RAISE_ASSUMED" | "SALARY_DIFFERS" | "SALARY_CONFLICT" | "SALARY_UNIDENTIFIED";

/**
 * What the statements say about a salary_net chain, derived on every read from the declarations, the eligible credits, statement coverage and the verification rules named by params_version (ADR-049). Nothing here is stored. Evidence is tied to the expected payday of each pay month, not to the credit's calendar month. `numeric_effect` says whether the forecast uses the declaration (applied) or only keeps it for checking (saved_only); a declaration is never a credited salary. In this release memory is saved only: numeric_effect is always saved_only, reasons is empty (no income is applied, so none of its warnings applies), and the financial results keep their own params_version (fc-0.3).
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
  /**
   * The version of the verification rules that produced this check (salary-check-0.1: tolerance 5%, window ±3 business days, conflict after 2 consecutive misses), not the financial parameters.
   */
  params_version: string;
}
export interface Payday {
  /**
   * YYYY-MM: the month whose payday (last weekday) first credits the salary. It funds the next pay cycle (ADR-049).
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
