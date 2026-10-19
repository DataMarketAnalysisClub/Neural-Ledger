/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Body of POST /v1/memory/proposals/{proposal_id}/confirm (from the copilot's card) and of PUT /v1/profile/income (from Perfil): the salary the user confirms, as they selected or typed it. User-only HTTP flows; the owner comes from authentication, never from the body. `base`, the previous salary and its pay month, is stored with the change in one atomic write when the chain has no version yet; it must start before the change. Neither is born verified. `expected_version` is compare-and-swap on the chain (409 VERSION_CONFLICT). The answer is memory_view.
 */
export interface IncomeDeclaration {
  salary_net: SalaryNet;
  base?: SalaryNet;
  expected_version: number;
  /**
   * Card confirmations only: the chat session, for the origin reference.
   */
  session_id?: string;
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
