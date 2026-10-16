/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * The body of a 429 answer (G07). The request went over the caller's or the client IP's budget for that kind of request in the current one-minute window and reached no use case. retry_after equals the Retry-After header: the seconds until the window ends.
 */
export interface RateLimited {
  status: "RATE_LIMITED";
  detail: string;
  retry_after: number;
}
