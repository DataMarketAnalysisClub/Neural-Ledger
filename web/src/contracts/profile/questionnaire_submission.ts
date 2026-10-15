/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

export type Answer = {
  question_id: string;
  option_id: string;
} & Answer1;
export type Answer1 =
  | {
      question_id?: "set_aside";
      option_id?: "small_part" | "about_half" | "most";
    }
  | {
      question_id?: "tight_month";
      option_id?: "pause" | "keep_cut_elsewhere" | "keep_as_intended";
    }
  | {
      question_id?: "goal_vs_room";
      option_id?: "spending_room" | "balance" | "goal_on_time";
    }
  | {
      question_id?: "surprise";
      option_id?: "very_stressed" | "uneasy_but_ok" | "calm";
    }
  | {
      question_id?: "habit";
      option_id?: "never_or_stopped" | "sometimes" | "regularly";
    };

/**
 * Request body of POST /v1/profile/questionnaire. Only the current version is accepted, with every question answered exactly once by a known option. The domain enforces the same rules and answers INVALID_INPUT (field 'version' or 'answers'); the tolerance is never taken from the client.
 */
export interface QuestionnaireSubmission {
  version: "pq-0.1";
  /**
   * @minItems 5
   * @maxItems 5
   */
  answers: Answer[];
}
