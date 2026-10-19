/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * The memory part of the user's data export (G02): every declaration of every chain, superseded versions included, in chain and version order. Derived conclusions are not exported: they are recomputed from the statements.
 */
export interface MemoryExport {
  catalog_version: "mem-0.1";
  declarations: MemoryDeclaration[];
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
