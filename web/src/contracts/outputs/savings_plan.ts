/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of compute_savings_plan. The envelope's snapshot_id (plan_...) is what propose_savings_rule takes.
 */
export interface SavingsPlan {
  profile: "conservative" | "moderate" | "aggressive";
  amount: number;
  start_month: string | null;
  share: number;
  lowest_available_in_window: number | null;
  required_monthly: number;
  allocation: {
    /**
     * 'reserve' or 'goal:<goal_id>'
     */
    bucket: string;
    monthly_amount: number;
  }[];
  requirements: {
    bucket: string;
    required_monthly: number;
    funded_monthly: number;
    /**
     * Month (YYYY-MM) the rule starts funding this bucket
     */
    funded_from: string | null;
  }[];
  goal_status: {
    goal_id: string;
    name?: string;
    target: number;
    saved: number;
    deadline: string;
    required_monthly?: number;
    funded_monthly?: number;
    projected_completion: string | null;
    on_track: boolean;
  }[];
  hard_rules_triggered: ("H1_RESERVE_BELOW_MINIMUM" | "H2_NO_POSITIVE_RULE")[];
}
