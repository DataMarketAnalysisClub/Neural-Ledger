/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

export type Id = string;

/**
 * data of GET /v1/profile/questionnaire: the current risk-tolerance questionnaire. The UI renders the copy keys; it asks nothing about income or wealth. Scores are shown for transparency only: the domain alone sums them and derives the tolerance (0-3 conservative, 4-7 moderate, 8-10 aggressive; a tight_month score of 0 caps the result at moderate). Answers stored against an older version stay interpretable through the domain registry. examples[0] is the exact current version.
 */
export interface Questionnaire {
  version: string;
  /**
   * @minItems 1
   */
  questions: Question[];
}
export interface Question {
  question_id: Id;
  copy_key: string;
  /**
   * @minItems 2
   */
  options: Option[];
}
export interface Option {
  option_id: Id;
  copy_key: string;
  score: number;
}
