/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * User-only PUT /v1/profile request. Display names use the domain's 1-40 code-point Unicode letters/spaces/periods/apostrophes/hyphens rule without controls or newlines. The domain derives declared_tolerance only from POST /v1/profile/questionnaire; neither tolerance nor questionnaire fields are writable here. The response reuses common/envelope and outputs/user_profile.
 */
export interface ProfileUpdate {
  display_name?: string;
  language?: string;
}
