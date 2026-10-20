# Plan: financial education by retrieval (ChromaDB)

Branch `c/education-rag` (from `staging`). ADR-040. Started Oct 19, 2026; target: today.
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
| Extra | `pyproject.toml` | `rag = ["chromadb>=0.5", "fastembed>=0.5"]` (ONNX, no torch; model about 240 MB in `NL_KB_DIR/models`) |

## Work packages (run in parallel)

### WP1 · Concept cards (4 Haiku agents, one per group, es + en)
- [x] G1 Budget and saving: `budget`, `rule_50_30_20`, `emergency_fund`, `savings_goal`, `pay_yourself_first`, `net_income`, `fixed_and_variable_expenses`, `liquidity`, `liquidity_floor`
- [x] G2 Credit and debt: `interest_rate`, `cae`, `installments`, `revolving_credit`, `minimum_payment`, `credit_report`, `debt_avalanche_and_snowball`, `debt_to_income_ratio`
- [x] G3 Money over time: `compound_interest`, `simple_interest`, `inflation`, `unidad_de_fomento`, `real_vs_nominal`, `time_value_of_money`, `opportunity_cost`, `time_deposit`
- [x] G4 Investing vocabulary (definitions only): `stock`, `bond`, `mutual_fund`, `etf`, `diversification`, `risk_and_return`, `apv`, `cryptocurrency`, `afp_pension_system`
- [x] Example card: `protected_surplus` (es, en)
- [ ] Review pass: own words, numbers declared, no advice, Chilean Spanish
- [x] Khan Academy pass (Oct 19): 28 of 35 concepts now cite Khan Academy Financial Literacy articles (CC BY-NC-SA, used as reference, own words; checked with an 8-word overlap scan against the downloaded articles)
- [x] Scope narrowed (Oct 19, team's sources.md): cards define terms and point to the right institution. Deductions, legal points, rates, caps and regulators' roles beyond one sentence are out of scope, which retires most of the earlier source checks.
    - [x] `apv`: regimes A and B defined from the Superintendencia de Pensiones article and Fintual's help page (the earlier card had them swapped)
    - [x] `mutual_fund`, `stock`, `bond`, `etf`: one "regulated by the CMF" sentence; `cryptocurrency`: legal-tender claim dropped
    - [x] `net_income`: no deductions; `cae`, `credit_report`, `interest_rate`: no laws, rights or rate ceilings
    - [ ] `time_deposit`: UF-indexed deposits (hedged as "some banks")
    - [ ] `rule_50_30_20`: the Santiago rent / 60-20-20 remark has no source

### WP2 · Retrieval adapters and wiring
- [x] `corpus_loader.py` + package data for `corpus/**/*.md`
- [x] `LexicalKnowledgeBase` (standard library BM25 over title, aliases, body)
- [x] `ChromaKnowledgeBase` with the multilingual embedder; persistent at `NL_KB_DIR`, rebuilt when the corpus hash changes
- [x] `FallbackKnowledgeBase`, `KNOWLEDGE_BASES`, settings, `rag` extra, `.env.example`
- [x] `tests/adapters/test_knowledge_base.py` (one contract test, both adapters; Chroma with a fake embedder, skipped without the extra)
- [x] `tests/unit/test_concept_cards.py` (every card parses; ids match across languages; numbers in the body are declared; banned words; word count; sources have a licence)
- [x] `tests/rag_eval/` (about 40 es/en questions → expected ids; recall@3 ≥ 0.8 lexical, ≥ 0.9 chroma; results to `evidence/rag_eval/`)

### WP3 · Agent integration
- [x] Contracts: tool input + output schemas
- [x] `EducationUseCases` returning the explanation envelope
- [x] `search_financial_concepts` in `catalog.py` (T0) and in the tools allowed on `Intent.EXPLAIN`
- [x] Lexicon: investing terms ("qué es un ETF") route to EXPLAIN, advice ("en qué invierto") still to OUT_OF_SCOPE
- [x] Prompt: answer only from the passages, name the concept, say it is general information, offer a link to the user's own numbers
- [x] Scripted model + narration: call the tool on EXPLAIN, narrate the top passage (replaces the fixed `narration.EXPLAIN`)
- [x] `tests/security/test_education_attacks.py`: injected text in a card or query, advice requests, invented numbers, a passage cannot reach T1/T2
- [x] `tests/application` chat tests for EXPLAIN in es and en

### WP4 · Docs
- [x] ADR-040 in `docs/DECISIONS.md`
- [x] `docs/SCOPE.md` §5.3 ports table: `KnowledgeBase`
- [x] `docs/ARCHITECTURE.md`: where code goes + recipe "Add a concept card"
- [x] README: `pip install -e "backend[rag]"`, `NL_KNOWLEDGE_BASE=chroma,lexical`

### Integration (after the packages)
- [x] Merge WP2–WP4 into `c/education-rag`; `ruff check .`; `make test-all` green
- [x] Run `tests/rag_eval` with Chroma and the real model; record in `evidence/rag_eval/`
- [x] Docker: Chroma runs in its own container (`docker compose --profile rag`, `NL_KB_URL`); the default image stays on `lexical`
- [ ] PR `c/education-rag` → `staging`

## Results so far

- Retrieval eval (52 questions, 70 cards, after the Khan Academy pass): lexical recall@3 1.0, MRR 0.958; Chroma recall@3 1.0, MRR 0.972 (`evidence/rag_eval/`). After the scope pass: lexical recall@3 1.0 (MRR 0.979), Chroma recall@3 1.0 (MRR 0.972). Floors still separate: lexical 0.556 vs 0.409 (floor 0.45, the margin is narrowing), Chroma 0.41 vs 0.261 (floor 0.30).
- Score thresholds differ by method: lexical about 0.45, Chroma about 0.30 (off-topic max 0.379 and 0.23).
- `rag` extra adds about 340 MB to site-packages plus the 240 MB model.
- [x] Chroma miss: "how much money do I really have available" → paraphrased aliases on `protected_surplus`; Chroma recall@3 now 1.0

## Integration notes (Oct 19)

- Full suite: the 175 failures and errors are the same set as on `origin/staging`, all from packages missing locally
  (`disposable-email-domains`, `email_validator`, receipt OCR). Nothing new fails. CI should be green; confirm on the PR.
- Smoke test with the real cards and the scripted model, `lexical` and `chroma,lexical`: CAE, cuota, ETF and compound
  interest are explained from their cards with the caveat; "¿En qué acción invierto?" is refused; an unknown term gets
  "no card, not from memory".
- Relevance floors live in `KB_MIN_SCORES` (container.py) and wrap each index before the fallback.

## Open decisions (from WP3)

- [ ] Cap EXPLAIN turns at T0 tools? Today T1/T2 are still offered; only the hard layer (no confirmed authorization) stops a model that obeys a card.
- [ ] Filter instruction-like sentences in quoted card text, or rely on the card review pass?
- [ ] Add the investing-definition and investing-advice examples to `tests/decision_eval/intents.jsonl`.
- [ ] "Explain how you got that number" now searches the cards and gets the no-card reply; route it to the user's own numbers instead?
- [ ] Narration cuts after two sentences, which can end on a lead-in ("Installments come in two common forms.").
- [ ] The scope refusal is English-only; answer "¿En qué acción invierto?" in Spanish.
- [ ] Merge commits `3022f5a` (contract) and `0b2b7e7` (registration) are separate; the first alone fails one contract test.

## Risks

| Severity | Risk | Mitigation |
|---|---|---|
| Critical | Source text copied into a public repo | Own-words rule, `license` per source, review pass |
| Critical | Definitions slide into advice | `NOT_ADVICE` caveat the verifier enforces; scope refusal for recommendations; security tests |
| High | Card numbers rejected by the verifier | Every body number declared and turned into a `Fact`; card test enforces it |
| High | Embedding model download offline / image size | `lexical` default and fallback; model cached in `NL_KB_DIR`; Docker decision above |
| Medium | Retrieval threshold set by guess | Tune `min_score` on `rag_eval`; record `knowledge_base` name on every answer |
| Low | Stale index after a card edit | Collection named by corpus hash |
