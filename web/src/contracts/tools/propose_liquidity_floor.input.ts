/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * Prepare a proposal for the user's own liquidity floor: the balance their checking account must keep at every pay-cycle trough, every month. Use it when the user asks to set or change their floor (piso, saldo minimo, minimum balance). `amount` must be the floor the user wrote in this message, in CLP; if they gave none, ask for it instead of choosing one. Nothing moves and nothing changes yet: the user must confirm the exact terms in the app's confirmation card, and once executed the floor replaces the default one in forecasts, plans and purchase checks.
 */
export interface ProposeLiquidityFloorInput {
  /**
   * The floor the user asked for, in CLP (integer), exactly as they wrote it.
   */
  amount: number;
}
