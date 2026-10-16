/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * The body of a 429 answer (G07). The request went over the caller's or the client IP's budget for that kind of request in the current one-minute window and reached no use case. retry_after equals the Retry-After header: the seconds until the window ends. status and message have the same shape as the auth error body, so clients read every error the same way.
 */
export interface RateLimited {
  status: "RATE_LIMITED";
  message: string;
  retry_after: number;
}
