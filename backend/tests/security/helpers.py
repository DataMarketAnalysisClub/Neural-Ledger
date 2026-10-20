from __future__ import annotations

from collections.abc import Sequence

from neural_ledger.adapters.outbound.decision.rules import RulesDecisionModel
from neural_ledger.adapters.outbound.persistence.memory import InMemoryConversationStore
from neural_ledger.adapters.outbound.system.ids import SequentialIds
from neural_ledger.application.conversation import ModelRequest, ModelTurn, ToolCall
from neural_ledger.application.services.decisions import DecisionService
from neural_ledger.application.use_cases.actions import ActorContext
from neural_ledger.application.use_cases.chat import ChatUseCase
from neural_ledger.domain.agent.policy import AP_0_1
from neural_ledger.domain.audit.events import Actor
from neural_ledger.domain.shared.serialization import to_primitive

USER = "camila"
SESSION = "s-security"


class ScriptedFakeLLM:
    """A language model that does exactly what the test says, like a compromised or lying model."""

    name = "fake"

    def __init__(self, turns: Sequence[ModelTurn]) -> None:
        self._turns = list(turns)
        self.requests: list[ModelRequest] = []

    def respond(self, request: ModelRequest) -> ModelTurn:
        self.requests.append(request)
        return self._turns.pop(0) if self._turns else ModelTurn("ok", (), "fake")


def call(name: str, **arguments) -> ModelTurn:
    return ModelTurn(None, (ToolCall(f"c_{name}", name, arguments),), "fake")


def say(text: str) -> ModelTurn:
    return ModelTurn(text, (), "fake")


def chat_with(services, adapters, llm, decision_models=None) -> ChatUseCase:
    decisions = DecisionService(decision_models or [RulesDecisionModel()], AP_0_1)
    return ChatUseCase(
        decisions, llm, services.registry, services.financial, adapters.audit_log,
        # The system's own id generator: a second sequence would reuse event ids, which a SQLite audit log refuses.
        InMemoryConversationStore(), adapters.clock, getattr(services.chat, "_ids", SequentialIds()), AP_0_1, services.memory,
    )


def user_ctx(session: str = SESSION) -> ActorContext:
    return ActorContext(session, USER, Actor.USER)


def agent_ctx(session: str = SESSION) -> ActorContext:
    return ActorContext(session, USER, Actor.AGENT)


def confirmed_authorization(services, session: str = SESSION):
    plan = services.financial.savings_plan(USER)
    proposal = services.actions.propose_savings_rule(agent_ctx(session), plan.snapshot_id).proposal
    outcome = services.actions.confirm(user_ctx(session), proposal.proposal_id, to_primitive(proposal.terms))
    assert outcome.status == "CONFIRMED"
    return outcome.authorization


def audit_kinds(adapters) -> list[str]:
    return [e.draft.kind.value for e in adapters.audit_log.events()]
