/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Stable codes for personal data removed from a bank statement when it was imported (ADR-028). In statement descriptions and transaction merchants they appear in square brackets, e.g. "Transf a [PERSON] [ID]". They contain no digits and the backend never translates them: clients render them in the user's language. PERSON: a name. ID: a RUT or RUN with a valid check digit. NUMBER: an account, card or other long number, or a RUT whose check digit fails. EMAIL. PHONE. ADDRESS: found only by an optional detector. Must equal PLACEHOLDER_CODES in domain/privacy/redaction.py.
 */
export type RedactionPlaceholder = "PERSON" | "ID" | "NUMBER" | "EMAIL" | "PHONE" | "ADDRESS";
