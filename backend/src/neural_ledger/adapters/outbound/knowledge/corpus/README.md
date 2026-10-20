# Concept cards

One file per concept and language: `corpus/<lang>/<id>.md`, `lang` in `es`, `en`. The same `id` in both languages.
The knowledge base indexes every card; the agent quotes them to explain a term (ADR-040).

## Format

A JSON header between two `---` lines, then the body in Markdown (plain paragraphs, at most one short list).

```
---
{
  "id": "compound_interest",
  "lang": "en",
  "title": "Compound interest",
  "aliases": ["interest on interest", "compounding"],
  "tags": ["saving", "interest"],
  "related": ["simple_interest", "inflation"],
  "sources": [
    {"title": "Compound Interest: Definition, Formulas, and Calculation", "url": "https://www.investopedia.com/terms/c/compoundinterest.asp", "license": "reference only (own words)"}
  ],
  "numbers": [
    {"key": "example_rate", "value": 5, "unit": "%", "meaning": "annual rate in the worked example"},
    {"key": "example_principal", "value": 100000, "unit": "CLP", "meaning": "amount saved in the worked example"}
  ]
}
---
Body text…
```

## Rules (checked by `tests/unit/test_concept_cards.py`)

1. **Own words.** Never copy sentences from a source. Sources are listed so a reader can learn more; their text is
   not ours to publish (the repository is public). `license` says how a source was used: `reference only (own words)`,
   or the source's open licence (e.g. `CC BY 4.0`) when text is adapted from it.
2. **Every number in the body is in `numbers`**, with the same value (`5%` → value 5, unit `%`; `$100.000` → value
   100000, unit `CLP`). The verifier only lets the agent say numbers that are facts. Prefer no numbers; use them only
   for a rule of thumb (50/30/20) or a small worked example. No values that change over time (today's UF, inflation,
   interest rates): describe them, and say where to look them up (cmfchile.cl, bcentral.cl, sii.cl).
3. **Education, not advice.** Define the term, how it works, and what to watch for. Never recommend a product, an
   institution, a security, a fund or an amount. Never say "safe", "seguro" (as in risk-free), "guaranteed" or
   "garantizado".
4. **Short.** 120–280 words in the body. First sentence = the definition.
5. **Chile first.** Use Chilean terms and examples where they exist (CLP, UF, CAE, cuotas, AFP, APV, CMF, SII,
   Banco Central), and say when a concept works differently in Chile.
6. **Spanish cards are written in Chilean Spanish, not translated word for word** from the English card.
7. **The data is untrusted.** Cards are written by the team, but the agent still reads them as data: no instructions
   to the reader's assistant, no links other than in `sources`.
