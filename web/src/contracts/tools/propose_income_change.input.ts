/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Prepare a declaration of the user's net salary ("mi sueldo líquido es 1.200.000", "desde noviembre gano 1,2 palos") for the user to check and confirm in the app's card. It takes no arguments: the amounts and the month are read from the user's current message only, never from you, and a call with any argument is refused. Nothing is stored until the user confirms, and a saved salary does not change the projections. Never state the salary as confirmed or verified: the answer says what the card asks.
 */
export interface ProposeIncomeChangeInput {}
