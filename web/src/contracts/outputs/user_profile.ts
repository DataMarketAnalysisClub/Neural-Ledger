/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of GET /v1/profile and of get_user_profile. The display name is user-typed and therefore untrusted text. The account email is never part of this record. The risk tolerance is derived from the questionnaire by the domain only.
 */
export type UserProfile = {
  user_id: string;
  /**
   * Validated by the domain: 1-40 code points of Unicode letters, spaces and . ' - only; no newlines or control characters.
   */
  display_name: {
    untrusted_text: string;
  };
  language: string;
  /**
   * null is read as conservative.
   */
  declared_tolerance: null | "conservative" | "moderate" | "aggressive";
  /**
   * Version the stored answers were given against. Any version known to the domain registry, not only the current one. null when the questionnaire was never answered.
   */
  questionnaire_version: string | null;
  questionnaire: Answer[];
};

export interface Answer {
  question_id: string;
  option_id: string;
}
