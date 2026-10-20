"""ADR-048: what a message says about a salary. The parser reads amounts and a pay month; it never decides which
amount is the old salary and which the new one, and it never invents an amount."""

from __future__ import annotations

import json
from datetime import date

import pytest

from neural_ledger.domain.agent.amounts import parse_income_statement
from neural_ledger.domain.memory.catalog import MAX_SALARY_NET
from neural_ledger.domain.shared.month import Month
from tests.conftest import CONTRACTS

TODAY = date(2026, 10, 19)  # payday of October 2026 is Friday the 30th


@pytest.mark.parametrize(
    ("text", "candidates"),
    [
        ("mi sueldo líquido es 1.200.000", (1_200_000,)),
        ("gano 1,2 palos", (1_200_000,)),
        ("me pagan $1.200.000 líquidos", (1_200_000,)),
        ("my net salary is 1.2M", (1_200_000,)),
        ("900 lucas al mes", (900_000,)),
        ("antes ganaba 1 palo y ahora 1.200.000", (1_000_000, 1_200_000)),  # the user picks, never the model
        ("1.200.000, sí, 1.200.000", (1_200_000,)),
        ("me subieron el sueldo", ()),  # ASK_AMOUNT: no amount is invented
        ("me subieron un 10%", ()),  # a percentage is not an amount
        ("gano 1.200.000,50", ()),  # nor is a fraction of a peso
        ("gano 200 palos", ()),  # above the catalog's limit
        ("desde noviembre 2026, el día 30", ()),  # years and days are not amounts
    ],
)
def test_amounts_are_read_as_written(text, candidates):
    assert parse_income_statement(text, TODAY).candidates == candidates


@pytest.mark.parametrize(
    ("text", "pay_month", "read_as"),
    [
        ("desde noviembre gano 1,2 palos", Month(2026, 11), "next_occurrence"),
        ("en octubre gano 1.2M", Month(2026, 10), "next_occurrence"),  # the current month is its next occurrence
        ("desde marzo gano 1.2M", Month(2027, 3), "next_occurrence"),  # never retroactive without a year
        ("desde marzo de 2026 gano 1.2M", Month(2026, 3), "explicit_year"),  # an explicit year wins
        ("en marzo 2025 ganaba 800.000", Month(2025, 3), "explicit_year"),
        ("starting January 2027 I earn 1.5M", Month(2027, 1), "explicit_year"),
        ("gano 900 lucas desde 2026-09", Month(2026, 9), "explicit_year"),
        ("sueldo 1.200.000 desde 11/2026", Month(2026, 11), "explicit_year"),
        ("en julio ganaba 1 palo pero desde diciembre 1,1", Month(2026, 12), "next_occurrence"),  # "desde" wins
        ("en julio y agosto gané 1 palo", Month(2027, 7), "next_occurrence"),  # otherwise the first month
        ("mi sueldo es 1.200.000", Month(2026, 10), "next_payday"),  # no month: the next payday's
        ("may I tell you my salary is 2M", Month(2026, 10), "next_payday"),  # "may" here is not May
        ("from May I earn 2M", Month(2027, 5), "next_occurrence"),
        ("pagado el 30/11/2026", Month(2026, 10), "next_payday"),  # a full date is not a pay month
    ],
)
def test_the_pay_month_is_interpreted_and_said(text, pay_month, read_as):
    statement = parse_income_statement(text, TODAY)
    assert (statement.pay_month, statement.read_as) == (pay_month, read_as)


@pytest.mark.parametrize(
    ("today", "pay_month"),
    [(date(2026, 10, 30), Month(2026, 10)), (date(2026, 10, 31), Month(2026, 11)), (date(2026, 12, 31), Month(2026, 12)), (date(2027, 1, 1), Month(2027, 1))],
)
def test_without_a_month_the_next_payday_decides(today, pay_month):
    assert parse_income_statement("gano 1.200.000", today).pay_month == pay_month


def test_a_month_without_a_year_rolls_over_the_new_year():
    assert parse_income_statement("desde enero 1.3M", date(2026, 12, 31)).pay_month == Month(2027, 1)


def test_the_parser_agrees_with_the_contracts():
    proposal = json.loads((CONTRACTS / "memory/income_proposal.schema.json").read_text(encoding="utf-8"))
    value = json.loads((CONTRACTS / "memory/memory_value.schema.json").read_text(encoding="utf-8"))
    assert MAX_SALARY_NET == value["$defs"]["salary_net"]["properties"]["amount"]["maximum"]
    assert MAX_SALARY_NET == proposal["properties"]["candidates"]["items"]["maximum"]
    read_as = {parse_income_statement(t, TODAY).read_as for t in ("1M", "desde marzo 1M", "desde marzo 2027 1M")}
    assert read_as == set(proposal["properties"]["effective_from"]["properties"]["read_as"]["enum"])
