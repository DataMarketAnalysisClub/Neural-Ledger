/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Warning codes about declared income (ADR-049). Each one says whether memory is applied or only saved; x-numeric-effect records which. The financial tools that use memory carry them as envelope warnings and the verifier makes the copilot mention them. INCOME_RAISE_ASSUMED: the typical scenario uses a declared amount the statements do not support yet; the conservative one keeps the supported level. SALARY_DIFFERS: the matched credits' median is below the declared amount and the lower is used. SALARY_CONFLICT: two consecutive eligible paydays without a matching credit; memory has no effect until the user confirms a new version. SALARY_UNIDENTIFIED: the salary could not be identified in every cycle of the estimation window, or there is no verified base; memory is saved with no effect.
 */
export type MemoryWarningCode = "INCOME_RAISE_ASSUMED" | "SALARY_DIFFERS" | "SALARY_CONFLICT" | "SALARY_UNIDENTIFIED";
