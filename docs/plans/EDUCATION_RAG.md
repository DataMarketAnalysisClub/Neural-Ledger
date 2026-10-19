# Plan: financial education by retrieval (ChromaDB)

Branch `c/education-rag` (from `staging`). ADR-039. Started Oct 19, 2026; target: today.
Tick a box when the item is merged into the branch.

## Goal

When the user asks what a term means ("¿qué es el interés compuesto?", "what is an ETF?"), the copilot explains it
from a small corpus of concept cards the team owns, retrieved with ChromaDB and a multilingual embedding model, instead of
from the model's memory. Explanations pass the same guards as every other reply: card numbers are facts, the
verifier runs, card text is untrusted data, and the answer is education, never advice.

## Decisions (Oct 19)

- **Embeddings:** multilingual (`paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions), so Spanish, English and later
  Chinese questions reach the same cards. The offline `lexical` adapter stays the default and the fallback.
- **Scope:** the agent may *define* investing terms (stock, bond, ETF, fondo mutuo, APV, crypto). It still refuses to
  recommend any of them; `REFUSAL_SCOPE` stays for advice.
- **Corpus:** Spanish and English from the start, same `id` in both. Written in our own words from public sources
  (Investopedia, CMF Educa, Banco Central, SII, Superintendencia de Pensiones), sources listed per card.

## Interfaces (fixed; every work package codes against these)

| Piece | Where | Shape |
|---|---|---|
| Card, passage, envelope | `domain/education/concepts.py` | `ConceptCard`, `CardNumber`, `Source`, `Passage(card, text, score)`, `explanation_envelope(passages, kb_name, min_score)`, `NOT_ADVICE`, `EDUCATION_VERSION` |
| Untrusted passage | `domain/agent/untrusted.py` | `wrap_passage(text)` → `{"untrusted_text": ...}`, max 1,500 chars |
| Port | `application/ports.py` | `KnowledgeBase.name`, `KnowledgeBase.search(query, lang, k) -> Sequence[Passage]`; `KnowledgeBaseUnavailable` |
| Card files | `adapters/outbound/knowledge/corpus/<lang>/<id>.md` | JSON header + Markdown body; rules in `corpus/README.md` |
| Loader | `adapters/outbound/knowledge/corpus_loader.py` | `load_cards(root=None) -> tuple[ConceptCard, ...]`, `corpus_hash(cards) -> str`; `ValueError` on a bad card |
| Offline adapter | `adapters/outbound/knowledge/lexical.py` | `LexicalKnowledgeBase(cards)`, name `lexical/<hash8>` |
| Chroma adapter | `adapters/outbound/knowledge/chroma.py` | `ChromaKnowledgeBase(cards, path, model)`, name `chroma/<model>/<hash8>`; one collection per corpus hash |
| Fallback | `application/services/knowledge_fallback.py` | `FallbackKnowledgeBase(chain)`, like `FallbackClassifier` |
| Settings | `bootstrap/config.py` | `NL_KNOWLEDGE_BASE` (default `lexical`, e.g. `chroma,lexical`), `NL_KB_DIR` (default `./var/chroma`), `NL_KB_EMBEDDING_MODEL` |
| Registry | `bootstrap/container.py` | `KNOWLEDGE_BASES = {"lexical": ..., "chroma": ...}`, built chain → variable `knowledge_base` |
| Use case | `application/use_cases/education.py` | `EducationUseCases(knowledge_base, min_score).explain(user_id, query, lang, k)` → `Envelope` |
| Tool | `contracts/tools/search_financial_concepts.input.schema.json`, `catalog.py` | T0; input `query` (string, ≤ 300), `lang` (`es`/`en`, optional), `k` (1–5, default 3) |
| Output contract | `contracts/outputs/financial_concepts.schema.json` | the envelope `data` above |
| Extra | `pyproject.toml` | `rag = ["chromadb>=0.5", <embedding runtime>]` |

## Work packages (run in parallel)

### WP1 · Concept cards (4 Haiku agents, one per group, es + en)
- [ ] G1 Budget and saving: `budget`, `rule_50_30_20`, `emergency_fund`, `savings_goal`, `pay_yourself_first`, `net_income`, `fixed_and_variable_expenses`, `liquidity`, `liquidity_floor`
- [ ] G2 Credit and debt: `interest_rate`, `cae`, `installments`, `revolving_credit`, `minimum_payment`, `credit_report`, `debt_avalanche_and_snowball`, `debt_to_income_ratio`
- [ ] G3 Money over time: `compound_interest`, `simple_interest`, `inflation`, `unidad_de_fomento`, `real_vs_nominal`, `time_value_of_money`, `opportunity_cost`, `time_deposit`
- [ ] G4 Investing vocabulary (definitions only): `stock`, `bond`, `mutual_fund`, `etf`, `diversification`, `risk_and_return`, `apv`, `cryptocurrency`, `afp_pension_system`
- [x] Example card: `protected_surplus` (es, en)
- [ ] Review pass: own words, numbers declared, no advice, Chilean Spanish

### WP2 · Retrieval adapters and wiring
- [ ] `corpus_loader.py` + package data for `corpus/**/*.md`
- [ ] `LexicalKnowledgeBase` (standard library BM25 over title, aliases, body)
- [ ] `ChromaKnowledgeBase` with the multilingual embedder; persistent at `NL_KB_DIR`, rebuilt when the corpus hash changes
- [ ] `FallbackKnowledgeBase`, `KNOWLEDGE_BASES`, settings, `rag` extra, `.env.example`
- [ ] `tests/adapters/test_knowledge_base.py` (one contract test, both adapters; Chroma with a fake embedder, skipped without the extra)
- [ ] `tests/unit/test_concept_cards.py` (every card parses; ids match across languages; numbers in the body are declared; banned words; word count; sources have a licence)
- [ ] `tests/rag_eval/` (about 40 es/en questions → expected ids; recall@3 ≥ 0.8 lexical, ≥ 0.9 chroma; results to `evidence/rag_eval/`)

### WP3 · Agent integration
- [ ] Contracts: tool input + output schemas
- [ ] `EducationUseCases` returning the explanation envelope
- [ ] `search_financial_concepts` in `catalog.py` (T0) and in the tools allowed on `Intent.EXPLAIN`
- [ ] Lexicon: investing terms ("qué es un ETF") route to EXPLAIN, advice ("en qué invierto") still to OUT_OF_SCOPE
- [ ] Prompt: answer only from the passages, name the concept, say it is general information, offer a link to the user's own numbers
- [ ] Scripted model + narration: call the tool on EXPLAIN, narrate the top passage (replaces the fixed `narration.EXPLAIN`)
- [ ] `tests/security/test_education_attacks.py`: injected text in a card or query, advice requests, invented numbers, a passage cannot reach T1/T2
- [ ] `tests/application` chat tests for EXPLAIN in es and en

### WP4 · Docs
- [ ] ADR-039 in `docs/DECISIONS.md`
- [ ] `docs/SCOPE.md` §5.3 ports table: `KnowledgeBase`
- [ ] `docs/ARCHITECTURE.md`: where code goes + recipe "Add a concept card"
- [ ] README: `pip install -e "backend[rag]"`, `NL_KNOWLEDGE_BASE=chroma,lexical`

### Integration (after the packages)
- [ ] Merge WP2–WP4 into `c/education-rag`; `ruff check .`; `make test-all` green
- [ ] Run `tests/rag_eval` with Chroma and the real model; record in `evidence/rag_eval/`
- [ ] Docker: decide whether the image ships the `rag` extra (size) or stays on `lexical`
- [ ] PR `c/education-rag` → `staging`

## Risks

| Severity | Risk | Mitigation |
|---|---|---|
| Critical | Source text copied into a public repo | Own-words rule, `license` per source, review pass |
| Critical | Definitions slide into advice | `NOT_ADVICE` caveat the verifier enforces; scope refusal for recommendations; security tests |
| High | Card numbers rejected by the verifier | Every body number declared and turned into a `Fact`; card test enforces it |
| High | Embedding model download offline / image size | `lexical` default and fallback; model cached in `NL_KB_DIR`; Docker decision above |
| Medium | Retrieval threshold set by guess | Tune `min_score` on `rag_eval`; record `knowledge_base` name on every answer |
| Low | Stale index after a card edit | Collection named by corpus hash |
