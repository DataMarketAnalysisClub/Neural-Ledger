/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Response envelope of every financial tool. Every number the agent may state is a fact; every assumption it must mention is a warning.
 */
export type Envelope = {
  status: "OK" | "INSUFFICIENT_DATA" | "INVALID_INPUT";
  params_version: string;
  /**
   * Tool-specific payload; see contracts/outputs. Null unless status is OK.
   */
  data?: {
    [k: string]: unknown;
  };
  /**
   * Hash of model source version, as_of, params_version and inputs. Stored by the audit log as forecast_snapshot_id.
   */
  snapshot_id?: string | null;
  as_of?: string | null;
  facts: Fact[];
  warnings: Caveat[];
  missing?: string[];
  field?: string | null;
  allowed?: string[];
  message?: string | null;
};

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
