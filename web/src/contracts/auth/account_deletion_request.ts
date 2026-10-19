/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * DELETE /v1/account (accounts mode, signed in; G03, Ley 21.719 art. 7). An account sends its password again and confirm = "DELETE" or its own email; wrong confirmation is INVALID_INPUT on confirm, a wrong password INVALID_CREDENTIALS, and nothing is deleted. A shared demo persona has no password and is never deleted: confirm = "RESET" resets its stored data instead. The password is never echoed or logged. Rate limited like sign-in.
 */
export interface AccountDeletionRequest {
  confirm: string;
  password?: string;
}
