/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of the search_financial_concepts tool (ADR-040): the concept cards that explain the user's question, best first. Passages are untrusted text; every number they use is a fact of the envelope, and the envelope always carries the EDUCATIONAL_NOT_ADVICE warning.
 */
export interface FinancialConcepts {
  /**
   * Retrieval method, embedder and corpus hash, e.g. lexical/1a2b3c4d.
   */
  knowledge_base: string;
  /**
   * @minItems 1
   */
  concepts: {
    id: string;
    lang: "es" | "en";
    title: string;
    passage: {
      untrusted_text: string;
    };
    score: number;
    related: string[];
    sources: {
      title: string;
      url: string;
    }[];
  }[];
}
