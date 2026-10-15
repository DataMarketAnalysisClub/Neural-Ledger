"""Importing card statements and Excel exports end to end (container wiring, synthetic files)."""

from __future__ import annotations

from importlib.util import find_spec

import pytest

from neural_ledger.domain.audit.events import AuditKind
from neural_ledger.domain.shared.envelope import Status
from tests.statement_samples import bice_xlsx, card_pdf, santander_xlsx

pytest.importorskip("pymupdf")
pytest.importorskip("pdfplumber")
needs_ml = pytest.mark.skipif(find_spec("sklearn") is None, reason="the ml extra (scikit-learn) is not installed")


@needs_ml
def test_card_pdf_imports_two_statements_with_obligations_and_posts_payments_as_movements(services):
    result = services.statements.import_statement("camila", card_pdf())
    assert result.status is Status.OK
    national, international = result.data.imports
    assert (national.statement.currency, international.statement.currency) == ("CLP", "USD")
    assert all(i.statement.verified and i.statement.account_type == "credit_card" and not i.duplicate for i in result.data.imports)

    o = national.statement.obligations
    assert (o.amount_due, o.minimum_due, o.due_date, o.installments_remaining) == (45_442, 5_000, "2026-09-15", 45_267)
    assert [(u.month, u.amount) for u in o.upcoming] == [("2026-09", 27_633), ("2026-10", 17_634)]
    assert o.installments[0].description == {"untrusted_text": "MERCADOPAGO*STORE"}
    facts = {f.key.rsplit(".", 1)[1]: f.value for f in result.facts if f.key.startswith(f"statement.{national.statement.statement_id}.")}
    assert (facts["amount_due"], facts["due_date"], facts["installments_remaining"]) == (45_442, "2026-09-15", 45_267)

    ledger = services.ledger.list_transactions("camila").data
    payments = [t for t in ledger.transactions if t.kind == "card_payment"]
    assert sorted((t.currency, t.amount, t.category, t.classifier) for t in payments) == [("CLP", 100_000, "movement", "rule"), ("USD", 2_241, "movement", "rule")]
    assert ledger.income == ()  # paying the card is not income
    spent: dict[str, int] = {}
    for t in ledger.spending:
        spent[t.currency] = spent.get(t.currency, 0) + t.spent
    assert spent == {"CLP": 17_755 + 27_633 + 54, "USD": 1_899}  # purchases + cuotas + fee − refund
    cuota = next(t for t in ledger.transactions if t.installment and t.installment.installment_number == 2)
    assert (cuota.amount, cuota.installment.installment_total, cuota.installment.original_amount) == (-10_000, 3, 30_000)

    events = [e for e in services.audit.raw() if e.draft.kind is AuditKind.STATEMENT_IMPORTED]
    assert len(events) == 2 and all("account_type=credit_card" in e.draft.detail for e in events)


def test_unbilled_card_export_is_stored_verified_but_never_posted(services):
    result = services.statements.import_statement("camila", bice_xlsx())
    (imported,) = result.data.imports
    assert imported.statement.provisional and imported.statement.verified and imported.statement.source == "xlsx"
    assert imported.statement.obligations is None  # an unbilled export prints no amount due
    assert imported.ledger.posted == 0
    (not_posted,) = [w for w in result.warnings if w.code == "NOT_POSTED"]
    assert "unbilled card movements" in not_posted.message
    assert services.ledger.list_transactions("camila").data.transactions == ()
    assert [s.provisional for s in services.statements.list_statements("camila").data] == [True]


@needs_ml
def test_checking_account_excel_export_is_posted_like_its_pdf(services):
    (imported,) = services.statements.import_statement("camila", santander_xlsx()).data.imports
    assert imported.statement.verified and imported.statement.account_type == "checking" and imported.statement.obligations is None
    assert imported.ledger.posted == 5
    kinds = sorted({t.kind for t in services.ledger.list_transactions("camila").data.transactions})
    assert kinds == ["income", "purchase"]


@needs_ml
def test_reimporting_a_card_pdf_is_a_duplicate_for_both_statements(services):
    services.statements.import_statement("camila", card_pdf())
    again = services.statements.import_statement("camila", card_pdf())
    assert [i.duplicate for i in again.data.imports] == [True, True]
    assert len(services.statements.list_statements("camila").data) == 2


def test_cli_prints_every_statement_and_its_obligations(services, tmp_path, capsys):
    from neural_ledger.adapters.inbound.cli.commands import main

    path = tmp_path / "tarjeta.pdf"
    path.write_bytes(card_pdf())
    assert main(services, ["import-statement", str(path), "--user", "camila"]) == 0
    out = capsys.readouterr().out
    assert out.count("cl_tarjeta_credito_pdf") == 2 and "credit_card" in out
    assert "obligations: due 45,442, minimum 5,000 CLP by 2026-09-15" in out
    assert "cuotas still to bill 45,267 CLP: 2026-09 27,633, 2026-10 17,634" in out
