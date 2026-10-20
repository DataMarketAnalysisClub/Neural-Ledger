/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * YYYY-MM: the month whose payday (last weekday) first credits the salary. It funds the next pay cycle (ADR-049).
 */
export type PayMonth = string;

/**
 * A typed value of the closed memory catalog mem-0.1 (ADR-048). One type today: salary_net, the user's declared net salary from a pay month on. Unknown types and fields are refused; a boolean is not an amount. A value is what the user declared, never a credited salary.
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
  effective_from: PayMonth;
}
