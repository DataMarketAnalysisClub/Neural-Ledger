"""Simulated sandbox bank (Role C). No real money, no real accounts.

It validates destinations again on its own side (defense in depth) and can be told to fail
the next call, which is how test S07 checks that nobody claims a failed execution succeeded.
Created rules live in a rule store: in memory by default, SQLite when persistence is durable,
so a restart never leaves an executed rule in the audit log that the bank has forgotten.
"""

from __future__ import annotations

import threading
from typing import Protocol

from ....domain.actions.terms import ActionTerms, ExecutionReceipt, SavingsRule
from ..persistence.memory import InMemorySavingsRuleStore

KNOWN_DESTINATIONS = frozenset({"sandbox_savings"})


class SavingsRuleStore(Protocol):
    def add(self, rule: SavingsRule) -> None: ...

    def count(self) -> int: ...

    def for_user(self, user_id: str) -> tuple[SavingsRule, ...]: ...


class SimulatedSandboxBank:
    def __init__(self, rules: SavingsRuleStore | None = None) -> None:
        self._rules: SavingsRuleStore = rules if rules is not None else InMemorySavingsRuleStore()
        self._lock = threading.Lock()
        self.fail_next = False

    def create_savings_rule(self, user_id: str, terms: ActionTerms, authorization_id: str, execution_id: str) -> ExecutionReceipt:
        with self._lock:
            if self.fail_next:
                self.fail_next = False
                return ExecutionReceipt(execution_id, False, error="SANDBOX_UNAVAILABLE")
            if terms.destination not in KNOWN_DESTINATIONS:
                return ExecutionReceipt(execution_id, False, error="UNKNOWN_DESTINATION")
            rule = SavingsRule(
                rule_id=f"rule_{self._rules.count() + 1:04d}",
                user_id=user_id,
                amount=terms.amount,
                currency=terms.currency,
                frequency=terms.frequency,
                source_account=terms.source_account,
                destination=terms.destination,
                effective_date=terms.effective_date,
                authorization_id=authorization_id,
            )
            self._rules.add(rule)
            return ExecutionReceipt(execution_id, True, reference=rule.rule_id)

    def active_rules(self, user_id: str) -> tuple[SavingsRule, ...]:
        return self._rules.for_user(user_id)
