/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

export interface Catalog {
  warnings: {
    code: string;
    source: string;
    trigger: string;
    must_mention: boolean;
    reaches_tool_envelope: boolean;
  }[];
  facts: {
    template: string;
    pattern: string;
    domains: {
      [k: string]: string;
    };
    unit: string;
    source: string;
  }[];
  error_fields: {
    status: "INVALID_INPUT" | "INSUFFICIENT_DATA";
    template: string;
    pattern: string;
    source: string;
  }[];
}
