/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * 200 body of GET /v1/me/export (G02, Ley 21.719 arts. 5 and 9), sent as a JSON file download (Content-Disposition: attachment). Everything stored about the signed-in user, from the same stores DELETE /v1/account erases: the account (null for a demo persona), the profile with its questionnaire answers, imported statements, ledger transactions, receipts, connections with their last answers, active savings rules, investments (the link without its access token, the latest snapshot and imported documents), memory (ADR-048: the consent with its counters and every declaration version, superseded ones included; null when the server has no memory) and the user's own audit events, the DATA_EXPORTED event of this export included. Never included: the password hash, session tokens, connection secrets or the investment access token. Sections hold the stored records as they are kept (ids, ISO 8601 times, money as integers in minor units); merchant, issuer and connection text is untrusted data. The format string changes whenever a section is added, renamed or changes shape. HTTP only: no agent tool reads it.
 */
export interface DataExport {
  format: "neural-ledger-export-2";
  exported_at: string;
  user_id: string;
  account: null | {
    email: string;
    created_at: string;
    sample_data: boolean;
  };
  profile: {} | null;
  statements: {}[];
  transactions: {}[];
  receipts: {}[];
  connections: {
    results: {}[];
  }[];
  savings_rules: {}[];
  investments: {
    link: {} | null;
    latest_snapshot: {} | null;
    documents: {}[];
  };
  memory: null | {
    consent: {
      consent: "missing" | "granted" | "revoked";
      consent_generation: number;
      memory_revision: number;
    };
    declarations: MemoryExport;
  };
  audit_events: {}[];
}
/**
 * The memory part of the user's data export (G02): every declaration of every chain, superseded versions included, in chain and version order. Derived conclusions are not exported: they are recomputed from the statements.
 */
export interface MemoryExport {
  catalog_version: "mem-0.1";
  declarations: MemoryDeclaration[];
}
/**
 * One stored version of a memory chain, as GET /v1/memory and the export show it (ADR-048). Only the user confirms a declaration; whether evidence supports it is derived on read (salary_check), never stored. The origin is an opaque reference: memory keeps neither the message nor its hash. The owner comes from authentication and is not part of the view.
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
  /**
   * YYYY-MM: the month whose payday (last weekday) first credits the salary. It funds the next pay cycle (ADR-049).
   */
  effective_from: string;
}
