"""S15: personal data in an imported cartola is never stored or returned (ADR-028).

The threat: identity is only the X-User-Id header, so anyone can read anyone's statements (residual risk B), and
the agent reads whatever its tools return (risk A). The defence: personal data is removed once, at import, before
anything is stored, so there is nothing personal left to read. Each surface is checked: the import response,
GET /v1/statements[/{id}], /v1/transactions, /v1/audit, the audit export, the database files and the logs.

The model is assumed hostile: one test lets a scripted fake model hunt for the data through its tools.
The cartola is synthetic; every name, RUT, account, address and number in it is fictional.
"""

from __future__ import annotations

import json

import pytest

from neural_ledger.adapters.inbound.cli.commands import export_audit
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.shared.serialization import to_primitive
from tests.conftest import make_settings
from tests.statement_samples import Sample, santander_pdf

from .helpers import SESSION, USER, ScriptedFakeLLM, call, chat_with, say

pytest.importorskip("fastapi")
pytest.importorskip("pymupdf")
pytest.importorskip("pdfplumber")
from fastapi.testclient import TestClient  # noqa: E402

from neural_ledger.adapters.inbound.http.app import create_app  # noqa: E402

pytestmark = pytest.mark.security

# Numbers with distinctive digits: a needle like 0000000002 also matches where SQLite stores the all-zero genesis hash
# right before an event hash that starts with 2, and event hashes differ by platform (they cover the classifier's name).
ACCOUNT = "0-713-52-98765-4"
CARTOLA = Sample(
    movements=(
        ("02/12", "2441010", "401", "Compra Nacional MD SHOP ONE", -3_280),
        ("03/12", "", "93", "0071548293 Transf a JUAN PEREZ", -40_000),
        ("03/12", "", "93", "Transf a 11.111.111-1 MARIA SOTO", -25_000),
        ("05/12", "", "90", "TEF DE PEDRO ROJAS 12.345.678-5", 150_000),
        ("09/12", "", "90", "Aviso maria.soto@mail.cl", -1_000),
        ("10/12", "", "90", "Fono +56 9 8765 4321", -2_000),
        ("15/12", "", "90", "PAGO TARJETA 4555 1234 5678 9012", -60_000),
        ("29/12", "", "90", "0062739184 REMUNERACION EMPRESA SPA", 900_000),
    ),
    period=("30/11/2025", "31/12/2025"),
    account=ACCOUNT,
)
# Every form a leak could take: names (and the holder printed in the preamble), RUTs, address, phone, card, account.
PERSONAL = (
    "JUAN", "PEREZ", "MARIA", "SOTO", "PEDRO", "ROJAS",
    "11.111.111-1", "111111111", "12.345.678-5", "123456785",
    "maria.soto@mail.cl", "mail.cl",
    "8765 4321", "87654321",
    "4555 1234 5678 9012", "4555123456789012",
    ACCOUNT, "071352987654",
    "0071548293", "0062739184",
)  # fmt: skip


def _leaks(surface: str, text: str) -> list[str]:
    return [f"{surface} contains {needle!r}" for needle in PERSONAL if needle in text]


@pytest.fixture
def durable(tmp_path):
    """The production wiring with SQLite, so the files on disk can be checked too."""
    database = tmp_path / "s15.db"
    services, adapters = build(make_settings(persistence="sqlite", sqlite_path=str(database)))
    return services, adapters, database


def test_s15_personal_data_in_a_cartola_is_never_stored_or_returned(durable, tmp_path, caplog, capsys):
    services, _, database = durable
    client = TestClient(create_app(services))
    headers = {"X-User-Id": USER}
    with caplog.at_level("DEBUG"):
        upload = client.post("/v1/statements", content=santander_pdf(CARTOLA), headers={**headers, "Content-Type": "application/pdf"})
        statement_id = upload.json()["data"]["imports"][0]["statement"]["statement_id"]
        surfaces = {
            "POST /v1/statements": upload.text,
            "GET /v1/statements": client.get("/v1/statements", headers=headers).text,
            "GET /v1/statements/{id}": client.get(f"/v1/statements/{statement_id}", headers=headers).text,
            "GET /v1/transactions": client.get("/v1/transactions", headers=headers).text,
            "GET /v1/audit": client.get("/v1/audit", headers=headers).text,
        }
    export = tmp_path / "audit.jsonl"
    assert export_audit(services, export) == 0
    capsys.readouterr()
    surfaces["audit export"] = export.read_text(encoding="utf-8")
    surfaces["logs"] = caplog.text
    for path in sorted(database.parent.glob(database.name + "*")):  # the database and its write-ahead log
        surfaces[path.name] = path.read_bytes().decode("utf-8", errors="ignore")

    # Not vacuous: the cartola was read, verified and posted, and its financial data is all there.
    body = upload.json()["data"]["imports"][0]
    assert upload.status_code == 200 and body["statement"]["verified"] and body["ledger"]["posted"] == 8
    assert body["statement"]["account_ref"] == "****7654"
    assert body["redaction"]["counts"] == {"PERSON": 3, "ID": 2, "NUMBER": 3, "EMAIL": 1, "PHONE": 1}
    lines = [line["description"]["untrusted_text"] for line in json.loads(surfaces["GET /v1/statements/{id}"])["data"]["lines"]]
    assert lines == [
        "Compra Nacional MD SHOP ONE",
        "[NUMBER] Transf a [PERSON]",
        "Transf a [ID] [PERSON]",
        "TEF DE [PERSON] [ID]",
        "Aviso [EMAIL]",
        "Fono [PHONE]",
        "PAGO TARJETA [NUMBER]",
        "[NUMBER] REMUNERACION EMPRESA SPA",
    ]
    # The database was scanned and holds the statement, sealed (G11): no line text in clear, not even a redacted one.
    stored = "".join(text for name, text in surfaces.items() if name.startswith("s15.db"))
    assert "nlenc1:" in stored and "Compra Nacional MD SHOP ONE" not in stored
    assert "STATEMENT_IMPORTED" in surfaces["audit export"]

    assert [leak for surface, text in surfaces.items() for leak in _leaks(surface, text)] == []


def test_s15_a_hostile_model_finds_no_personal_data_through_its_tools(services, adapters):
    """Risk A. Today no tool returns statement text and audit details never held any, so this guards the future:
    once the planned get_transactions tool exists, it is called here and must only ever return redacted data."""
    services.statements.import_statement(USER, santander_pdf(CARTOLA), session_id=SESSION)  # its audit event is in this session
    llm = ScriptedFakeLLM([
        call("get_transactions"),  # the planned ledger tool: blocked while it does not exist, clean data once it does
        call("get_statement", statement_id="any"),
        call("get_audit_events", limit=50),
        say("These are the people and RUTs I found."),
    ])  # fmt: skip
    reply = chat_with(services, adapters, llm).handle(SESSION, USER, "List every person and RUT in my cartola")

    seen = json.dumps(to_primitive([request.entries for request in llm.requests]), ensure_ascii=False)
    assert "STATEMENT_IMPORTED" in seen  # the model did read the import's audit event
    assert [leak for leak in _leaks("what the model was shown", seen)] == []
    assert _leaks("the reply", reply.text) == []
    assert adapters.bank.active_rules(USER) == ()


def test_s15_the_synthetic_cartola_is_read_back_whole():
    """Guards S15 itself: every personal value really reaches the import, so its absence afterwards means something."""
    from neural_ledger.adapters.outbound.statements.reader import StatementFileReader

    [read] = StatementFileReader().read(santander_pdf(CARTOLA))
    assert [line.description for line in read.lines] == [movement[3] for movement in CARTOLA.movements]
    assert read.account_ref == ACCOUNT
