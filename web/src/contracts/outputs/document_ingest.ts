/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of POST /v1/documents (ADR-039): a file dropped on the copilot, routed to the statement import, read as a receipt or imported as an investment document (ADR-044, investment), with every workflow step for the UI and the spending check-in that follows. Models only route the file and guess a category; amounts come from the document and every figure from the engine. A receipt's store name is untrusted third-party text.
 */
export interface DocumentIngest {
  kind: "statement" | "receipt" | "investment";
  /**
   * @minItems 2
   */
  steps: Step[];
  /**
   * The statement import (as POST /v1/statements answers it) when kind is statement, else null.
   */
  statement: StatementImport | null;
  receipt: Receipt | null;
  /**
   * Null when the user has no financial model yet.
   */
  spending: SpendingCheck | null;
  /**
   * The investment document import (ADR-044) when kind is investment, else null. Nothing of it is posted to the ledger or counted as spending.
   */
  investment?: InvestmentDocumentImport | null;
}
export interface Step {
  key: "read" | "route" | "verify" | "redact" | "duplicate" | "categorize" | "match" | "spending" | "investments";
  status: "done" | "warning" | "skipped" | "failed";
  /**
   * A label or a number as text (pdf, receipt, stamp, groceries, outside, 27719, holdings), never prose.
   */
  value: string | null;
  /**
   * The rule or model that answered (rules, format, jev:..., naive_bayes@...).
   */
  by: string | null;
  confidence: number | null;
}
/**
 * data of POST /v1/statements: one entry per statement in the file, in file order (a card statement PDF holds a national and an international one). Personal data is removed before anything is stored, and a statement that cannot be redacted fails the whole import (ADR-028). An unverified or provisional statement is still stored but not posted to the transaction ledger; a duplicate stores nothing new.
 */
export interface StatementImport {
  /**
   * @minItems 1
   */
  imports: Imported[];
}
export interface Imported {
  duplicate: boolean;
  statement: Summary;
  /**
   * How personal data was removed from this import. Null for a duplicate: nothing new was redacted or stored.
   */
  redaction: {
    /**
     * Version of the built-in rules, which always run, e.g. pii-0.1.
     */
    rules: string;
    /**
     * Optional detector run after the rules (NL_PII_DETECTOR): none or azure_language.
     */
    detector: string;
    /**
     * True when the detector was unavailable and only the rules ran (see the REDACTION_DEGRADED warning).
     */
    degraded: boolean;
    /**
     * Placeholders inserted per code; codes with none are left out. Counts only, never the text they replaced.
     */
    counts: {
      [k: string]: number;
    };
  } | null;
  /**
   * Posting to the transaction ledger. posted = 0 and classifier = null when the statement was not posted (see the NOT_POSTED warning).
   */
  ledger: {
    /**
     * Transactions this statement contributes to the ledger.
     */
    posted: number;
    /**
     * Of those, added by this import (0 on a re-import).
     */
    new: number;
    /**
     * Charges whose category was not accepted.
     */
    uncategorized: number;
    /**
     * Method and training-data hash that chose the categories, e.g. naive_bayes@3f2a9c1d04be.
     */
    classifier: string | null;
  };
}
export interface Summary {
  statement_id: string;
  /**
   * Code of the Bank layout that read it, e.g. santander_cl_cuentamatica.
   */
  bank: string;
  /**
   * Masked at import: only the last 4 digits (or the 4 characters a bank already left visible) are kept, e.g. ****3456 (ADR-028).
   */
  account_ref: string;
  /**
   * From the layout that read it. A credit card statement carries obligations and its payments are never income.
   */
  account_type: "checking" | "savings" | "credit_card";
  currency: string;
  period_start: string;
  period_end: string;
  source: "text" | "ocr" | "xlsx";
  imported_at: string;
  line_count: number;
  /**
   * Sum of charges read from the lines (positive).
   */
  total_debits: number;
  total_credits: number;
  /**
   * As printed; a card's previous billed debt, negative.
   */
  opening_balance: number | null;
  /**
   * As printed; a card's billed debt, negative.
   */
  closing_balance: number | null;
  /**
   * Unbilled movements (a card export of the open period): checked and stored, never posted to the ledger.
   */
  provisional: boolean;
  /**
   * True only if every printed total and daily balance matched the lines.
   */
  verified: boolean;
  issues: {
    code:
      | "TOTAL_DEBITS"
      | "TOTAL_CREDITS"
      | "CLOSING_BALANCE"
      | "DAILY_BALANCE"
      | "OUT_OF_PERIOD"
      | "NO_SUMMARY"
      | "LOW_CONFIDENCE"
      | "SECTION_TOTAL"
      | "INSTALLMENT_SCHEDULE";
    message: string;
    expected: number | null;
    found: number | null;
    on: string | null;
  }[];
  /**
   * Credit card statements only (null on a checking account, and on unbilled exports, which print no amount due).
   */
  obligations: null | Obligations;
}
/**
 * What the card statement says the holder owes. Positive magnitudes in the statement's currency; null when not printed. amount_due is the statement's closing debt, which reconciliation checks.
 */
export interface Obligations {
  amount_due: number | null;
  minimum_due: number | null;
  due_date: string | null;
  credit_limit: number | null;
  credit_used: number | null;
  credit_available: number | null;
  /**
   * Cuotas still to bill after this statement, computed from its cuota lines.
   */
  installments_remaining: number;
  installments: {
    line_index: number;
    description: {
      untrusted_text: string;
    };
    number: number;
    total: number;
    installment_amount: number;
    original_amount: number;
    remaining_amount: number;
  }[];
  /**
   * Cuotas due per later statement month, computed; when the bank prints its own schedule, reconciliation checks these against it (INSTALLMENT_SCHEDULE).
   */
  upcoming: {
    month: string;
    amount: number;
  }[];
}
export interface Receipt {
  receipt_id: string;
  issuer: {
    untrusted_text: string;
  };
  issued_on: string | null;
  total: number | null;
  currency: "CLP";
  folio: string | null;
  /**
   * The SII stamp (timbre electrónico) was decoded and confirms the print.
   */
  stamped: boolean;
  /**
   * manual: an expense the user told the copilot about and confirmed.
   */
  source: "text" | "ocr" | "manual";
  /**
   * Cash is never matched with a statement charge.
   */
  payment: "cash" | "card" | "unknown";
  category: string;
  classifier: string;
  /**
   * Only a verified receipt is counted.
   */
  verified: boolean;
  issues: {
    code: "TOTAL_MISSING" | "DATE_MISSING" | "DATE_IN_FUTURE" | "TAX_MISMATCH" | "STAMP_MISMATCH";
    message: string;
  }[];
  /**
   * The statement charge that already records this purchase: the receipt is then counted once, as that charge.
   */
  matched_transaction: string | null;
  duplicate: boolean;
  /**
   * The user typed or confirmed its total or date in the app.
   */
  corrected: boolean;
  /**
   * Part of this cycle's logged spending: verified, not on a statement, dated inside the cycle. A receipt from an earlier cycle is kept but does not change today's figure.
   */
  counted: boolean;
}
export interface SpendingCheck {
  cycle: string;
  window_start: string;
  /**
   * The eve of the next payday: the cycle runs from window_start (payday) to here.
   */
  window_end: string;
  /**
   * The forecast projects this cycle, so an overspend lowers the protected surplus; false for a cycle before the forecast's first one.
   */
  projected: boolean;
  today: string;
  days_left: number;
  /**
   * Conservative (P80) variable spending the forecast counts on for the cycle, CLP.
   */
  assumed: number;
  logged: number;
  logged_items: number;
  /**
   * assumed - logged; negative once spending passed the assumption.
   */
  left: number;
  /**
   * left // days_left, rounded down; 0 once nothing is left.
   */
  per_day: number;
  overspend: number;
  protected_surplus: number;
  /**
   * protected_surplus - overspend in a projected cycle (else protected_surplus); negative means a conservative month breaches the floor.
   */
  surplus_after: number;
  categories: {
    category: string;
    assumed: number;
    logged: number;
  }[];
}
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
