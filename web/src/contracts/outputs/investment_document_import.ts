/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * The investment part of POST /v1/documents (ADR-044): a statement or transactions certificate the provider issued, read by the backend (never by a model), checked to add up and kept only when it does. The holder's name and RUT are never read. overview is what get_investments reads from now on (null while nothing usable is imported). Warnings add INVESTMENT_DOCUMENT_UNVERIFIED or INVESTMENT_DOCUMENT_DUPLICATE to the overview's.
 */
export interface InvestmentDocumentImport {
  document: InvestmentDocument;
  /**
   * The same document was already imported; nothing changed.
   */
  duplicate: boolean;
  overview: InvestmentOverview | null;
}
/**
 * An investment document the user imported (ADR-044), without its rows: Fintual's investment statement (holdings: the balance of every fund and series on one day) or its transactions certificate (movements: every contribution and withdrawal). Only a verified document is kept and used; issues say why one is not.
 */
export interface InvestmentDocument {
  document_id: string;
  provider: "fintual";
  kind: "holdings" | "movements";
  /**
   * The statement's day, or the certificate's last movement; null when it could not be read.
   */
  as_of: string | null;
  /**
   * Null for a document that was not kept.
   */
  imported_at: string | null;
  rows: number;
  /**
   * It adds up; only a verified document is kept and used.
   */
  verified: boolean;
  issues: {
    code:
      | "NO_ROWS"
      | "DATE_MISSING"
      | "DATE_OUT_OF_RANGE"
      | "OUT_OF_RANGE"
      | "TOTAL_MISMATCH"
      | "BALANCE_MISMATCH"
      | "SHARES_DO_NOT_CHAIN"
      | "PESOS_MISMATCH"
      | "INTERNAL_UNBALANCED";
    message: string;
  }[];
}
/**
 * data of get_investments and GET /v1/investments (ADR-044): the user's investments at a provider. source statement: the newest verified investment statement (balances per fund and series on as_of) and transactions certificate (contributions and withdrawals) the user imported, read by the backend and checked to add up; each goal's value is its part of the printed balances by its shares, and only when both documents describe the same shares (documents_agree); the gain only when the certificate also starts when the account opened (contributions.complete). source sync: the last snapshot of a linked account (in development), as the provider reported it at synced_at. Amounts are integers in pesos; totals, contributions, averages and gains are computed by the backend; shares and values per share are exact decimal text. Goal names are the user's labels at the provider, wrapped as untrusted text. stale: a sync over 24 hours old or a statement over a month old; synthetic: the offline sandbox fixture. Facts (unit = currency unless noted): investments.total_value, investments.funds (count), investments.fund.<fund_id>.value, investments.contributed, investments.withdrawn, investments.total_deposited (net), investments.contributions and investments.withdrawals (count), investments.monthly_contribution, investments.history_months and investments.contribution_months (count), investments.total_gain, investments.gain_pct (%), investments.goals (count), investments.goal.<goal_id>.value|deposited|gain. Warnings: INVESTMENTS_FROM_STATEMENT or INVESTMENTS_AS_REPORTED always, and INVESTMENTS_STATEMENT_OLD, INVESTMENTS_NO_BALANCE, INVESTMENTS_NO_HISTORY, INVESTMENTS_PARTIAL_HISTORY, INVESTMENTS_DOCUMENTS_DISAGREE, INVESTMENTS_SYNTHETIC and INVESTMENTS_STALE when they apply. With nothing imported or linked the envelope is INSUFFICIENT_DATA with missing ["investment_account"].
 */
export interface InvestmentOverview {
  provider: "fintual";
  currency: string;
  source: "statement" | "sync";
  /**
   * The day the values describe: the statement's day (else the certificate's last movement), or the sync's day.
   */
  as_of: string;
  synced_at: string | null;
  synthetic: boolean;
  stale: boolean;
  /**
   * Null when only the transactions certificate was imported.
   */
  total_value: number | null;
  /**
   * Net contributions: contributions less withdrawals.
   */
  total_deposited: number | null;
  /**
   * total_value - total_deposited; negative is a loss.
   */
  total_gain: number | null;
  /**
   * total_gain / total_deposited x 100, one decimal, rounded half up.
   */
  gain_pct: number | null;
  /**
   * @maxItems 50
   */
  goals: Goal[];
  /**
   * @maxItems 60
   */
  funds: Fund[];
  contributions: Contributions | null;
  /**
   * The documents these figures come from (statement source).
   *
   * @maxItems 2
   */
  documents: InvestmentDocument[];
  /**
   * The statement and the certificate describe the same shares per fund and series; null unless both are imported.
   */
  documents_agree: boolean | null;
}
export interface Goal {
  goal_id: string;
  name: {
    untrusted_text: string;
  };
  /**
   * Null when the imported documents do not describe the same shares.
   */
  value: number | null;
  /**
   * Net contributions (contributions less withdrawals, moves between the user's goals included), when known.
   */
  deposited: number | null;
  /**
   * value - deposited.
   */
  gain: number | null;
}
export interface Fund {
  fund_id: string;
  /**
   * The provider's fund name, e.g. Risky Norris.
   */
  fund: string;
  series: string;
  shares: string;
  /**
   * Pesos per share on as_of.
   */
  share_value: string;
  /**
   * The printed balance.
   */
  value: number;
}
/**
 * Money from and to the bank in the transactions certificate; moves between the user's own goals are not contributions.
 */
export interface Contributions {
  first_day: string;
  last_day: string;
  contributions: number;
  withdrawals: number;
  contributed: number;
  withdrawn: number;
  net_contributed: number;
  /**
   * Calendar months from first_day to last_day, both included.
   */
  months: number;
  active_months: number;
  /**
   * contributed / months, rounded half up.
   */
  monthly_average: number;
  last_contribution: string | null;
  /**
   * Every goal, fund and series starts from zero shares: the certificate holds the whole history.
   */
  complete: boolean;
}
