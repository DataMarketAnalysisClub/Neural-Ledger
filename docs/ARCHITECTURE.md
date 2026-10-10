# Architecture guide (for developers)

The *why* is in [SCOPE.md §5](SCOPE.md#5-architecture). This page is the *how*: where code goes and the recipes for the changes you will make most often.

## The one rule

```
adapters  ──►  application  ──►  domain
(FastAPI,       (use cases,       (pure rules:
 SQLite,         ports,            money, forecast,
 LLM, Jev)       services)         gate, audit)
                      ▲
bootstrap ────────────┘  (wires concrete adapters into use cases; nothing imports bootstrap)
```

- `domain/` and `application/` import **only the Python standard library**. No FastAPI, no pydantic, no SDKs, no `datetime.now()`, no randomness, no file or network access.
- Adapters implement ports. Inbound adapters (HTTP, CLI) call use cases through `ApplicationServices`. Outbound adapters (LLM, Jev, DB, bank) are passed into use cases by `bootstrap/container.py`.
- `tests/architecture/test_dependency_rule.py` fails the build if any of this is broken.

## Where does X go?

| You are adding… | Put it in | Test it in |
|---|---|---|
| A formula, threshold or financial rule | `domain/finance/` (+ parameter in `params.py`) | `tests/golden`, `tests/unit/test_invariants.py` |
| A new permission rule or block reason | `domain/permissions/policy.py` | `tests/security` |
| A new step in a flow (e.g. "compare two purchases") | a method in `application/use_cases/*` | `tests/application` |
| A new agent tool | contract + catalog entry (recipe below) | `tests/contract`, `tests/security` |
| A new LLM provider | `adapters/outbound/llm/<provider>.py` implementing `LanguageModel` | a fake-server test, plus manual |
| The Jev integration | `adapters/outbound/decision/jev.py` | `tests/security` (S10) |
| A new database | `adapters/outbound/persistence/<db>.py` | add it to the `stores` fixture in `tests/adapters` |
| An HTTP endpoint | `adapters/inbound/http/app.py` (thin: parse → use case → `to_primitive`) | `tests/http` |
| A config switch | `bootstrap/config.py` + `.env.example` + `container.py` | — |
| A frontend screen | `web/`, consuming `contracts/` | — |

## Recipes

### Add an agent tool
1. Write `contracts/tools/<name>.input.schema.json` with `description` (3–4 sentences the model will read), `x-tier`, `x-owner` and the input schema. If it returns new data, add `contracts/outputs/<name>.schema.json`.
2. Implement the behaviour as a use-case method returning an `Envelope` (facts and warnings) or an `ActionOutcome`.
3. Register it in `application/catalog.py` with its tier. The tier lives in code; the contract test checks that it matches `x-tier`.
4. If the scripted model should use it, add a step in `adapters/outbound/llm/scripted.py`, and teach the narrator in `application/services/narration.py` to describe it.
5. Run `make test`: the contract test checks names, tiers and output schemas.

### Add an LLM provider (Role B)
Implement `respond(request: ModelRequest) -> ModelTurn` and map `UserEntry` / `AssistantEntry` / `ToolResultEntry` to the provider's format (see `anthropic.py`). Raise `LanguageModelUnavailable` on any network or API error so `FallbackLanguageModel` can switch to the scripted model. Add a value for `NL_LLM` in `container.py`.

### Implement Jev (Role B)
Map `ChoiceQuestion → Choice`, `ScoreQuestion → Score`, `YesNoQuestion → Noul`, and return `Judgment(label, probabilities, confidence, source)`. Confirm field names in the TypeSafe docs first. Raise `DecisionModelUnavailable` on errors. Then set `NL_DECISION_CHAIN=jev,rules`.

### Switch from fixtures to the ledger (Roles A, C, E)
1. E: the generator writes `data/ledgers/<user>.json` (a `LedgerSnapshot`) from the calibration targets.
2. A: implement `domain/finance/estimation.py:estimate_model`. Remove the `xfail` in `tests/golden/test_estimation.py`; it must pass.
3. C: add a `LedgerModelSource` adapter (load snapshot → `estimate_model`) and `NL_MODEL_SOURCE=ledger` in `container.py`. No use case changes.

## Domain model (for the empty Class Diagram page)

```mermaid
classDiagram
  class FinancialModel {
    user_id; currency; as_of; first_cycle
    balances; income; commitments; spend; goals
    commitments_due(month); debt_service_due(month)
  }
  class Commitment { type; amount; first_due; last_due; due_in(month) }
  class SpendModel { categories; seasonal_factors; total(month, quantile) }
  class Forecast { scenario; floor; cycles; breaches; lowest }
  class PurchaseSimulation { quote; verdict; impacts; alternatives }
  class SurplusResult { protected_surplus; binding_month; monthly_free_flow }
  class CapacityAssessment { level; binding_factors; factors }
  class SavingsPlan { amount; start_month; allocation; requirements }
  class ActionTerms { action; amount; currency; frequency; source; destination; effective_date }
  class Proposal { proposal_id; terms; source_snapshot_id; expires_at; status }
  class Authorization { authorization_id; terms; action_hash; expires_at; consumed_at }
  class AuditEvent { sequence; prev_hash; event_hash; draft }
  FinancialModel "1" o-- "*" Commitment
  FinancialModel o-- SpendModel
  FinancialModel ..> Forecast : project()
  FinancialModel ..> PurchaseSimulation : simulate_purchase()
  FinancialModel ..> SurplusResult : protected_surplus()
  FinancialModel ..> CapacityAssessment : assess_capacity()
  FinancialModel ..> SavingsPlan : size_plan()
  SavingsPlan ..> ActionTerms : terms_from_plan()
  ActionTerms --o Proposal
  Proposal ..> Authorization : user confirms
  Authorization ..> AuditEvent : every step
```

## Use cases (for the empty Use Cases page)

| Actor | Use case | Tier | Entry point |
|---|---|---|---|
| User | Ask a question in chat | — | `POST /v1/chat` |
| User | See balance, commitments, forecast | T0/T1 | `GET /v1/state`, `/v1/commitments`, `/v1/forecast` |
| User | Simulate a purchase | T1 | `POST /v1/simulate-purchase` |
| User | See protected surplus and capacity | T1 | `GET /v1/protected-surplus`, `/v1/capacity` |
| Agent | Propose a savings rule from a plan | T1 | tool `propose_savings_rule` |
| User | Confirm the exact terms | T2 | `POST /v1/actions/proposals/{id}/confirm` (UI only) |
| User or agent | Execute a confirmed action | T2 | `POST /v1/actions/execute`, tool `execute_sandbox_action` |
| Agent | Anything in T3 | T3 | always blocked and audited |
| Judge or user | Inspect the audit log and verify the chain | T0 | `GET /v1/audit`, `/v1/audit/verify` |

## Runtime modes

| Mode | Settings | Use |
|---|---|---|
| Offline (default) | `NL_LLM=scripted`, `NL_DECISION_CHAIN=rules` | CI, `docker compose up` without keys, demo recording, S10 |
| Live | `NL_LLM=anthropic` (or another provider), `NL_DECISION_CHAIN=jev,rules` | The real demo; falls back to offline pieces on outages |
| Deterministic | `NL_CLOCK=fixed`, `NL_IDS=sequential` | Reproducible recordings and evidence |

`GET /health` reports the mode, so the demo never runs in the wrong one by accident.
