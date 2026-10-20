/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Warning codes about declared income (ADR-049). Each one says whether memory is applied or only saved; x-numeric-effect records which. The financial tools that use memory carry them as envelope warnings and the verifier makes the copilot mention them. INCOME_RAISE_ASSUMED: the typical scenario uses a declared amount the statements do not support yet; the conservative one keeps the supported level. SALARY_DIFFERS: the matched credits' median is below the declared amount and the lower is used. SALARY_CONFLICT: two consecutive eligible paydays without a matching credit; memory has no effect until the user confirms a new version. SALARY_UNIDENTIFIED: the salary could not be identified in every cycle of the estimation window, or there is no verified base; memory is saved with no effect.
 */
export type MemoryWarningCode = "INCOME_RAISE_ASSUMED" | "SALARY_DIFFERS" | "SALARY_CONFLICT" | "SALARY_UNIDENTIFIED";

/**
 * data of the copilot's get_user_memory tool (T0, ADR-048): typed values and derived conclusions only. No text, no glosa, no origin and no store payload reaches the model. Without the memory consent, or for a shared persona, `items` is empty. In this release memory is saved only: numeric_effect is saved_only and reasons is empty. When every version starts later than today's pay month, the item is the next one and upcoming is null.
 */
export interface MemorySummary {
  catalog_version: "mem-0.1";
  consent: "granted" | "missing" | "revoked";
  items: Item[];
}
export interface Item {
  type: "salary_net";
  /**
   * Declared by the user, never a credited salary.
   */
  amount: number;
  /**
   * YYYY-MM: the month whose payday (last weekday) first credits the salary. It funds the next pay cycle (ADR-049).
   */
  effective_from: string;
  status: "declared" | "verified" | "conflict";
  numeric_effect: "applied" | "saved_only";
  reasons: MemoryWarningCode[];
  upcoming: {
    amount: number;
    /**
     * YYYY-MM: the month whose payday (last weekday) first credits the salary. It funds the next pay cycle (ADR-049).
     */
    effective_from: string;
  } | null;
}
