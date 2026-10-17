"""C01-C12 and G01-G12: what Chilean law and the security standards ask of the system, as tests.

Every test names the norm it gives evidence for. A control that is built is a plain test. A duty that is
not built yet is a strict xfail marked GAP: CI stays green, the gap stays visible, and the day the control
lands the test XPASSes, which fails the run until its marker is removed.

Norms (docs/SECURITY.md, "Compliance map"):
- Ley 19.628 as amended by Ley 21.719 (personal data; in force 2026-12-01). Article numbers follow the
  Biblioteca del Congreso Nacional's summary of the law (Informe 12-25): art. 3 principles, arts. 5-9 rights,
  art. 12 consent, arts. 14 bis-14 sexies duties, arts. 17-19 financial data.
- Ley 19.496, art. 3 b): truthful and timely information to consumers.
- Ley 21.663 (cybersecurity framework): detection and reporting of incidents.
- PCI DSS v4.0 (card data), OWASP ASVS 5.0, OWASP API Security Top 10 (2023), OWASP Top 10 for LLM
  Applications (2025).

This is engineering evidence for counsel to review, not legal advice.
"""

from __future__ import annotations

import ast
import re
import subprocess
import warnings
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from neural_ledger.adapters.inbound.http.app import create_app
from neural_ledger.bootstrap.config import DEV_SECRET, Settings
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.shared.serialization import to_primitive
from tests.conftest import make_settings

from .helpers import SESSION, USER, ScriptedFakeLLM, chat_with, say

pytestmark = pytest.mark.security

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "backend/src/neural_ledger"
needs_pdf = pytest.mark.skipif(
    not all(__import__("importlib").util.find_spec(m) for m in ("pymupdf", "pdfplumber")), reason="needs the backend's `pdf` extra"
)

# What the synthetic statements print about their (fictional) holder. None of it may be stored.
HOLDER_IDENTITY = ("PEREZ", "11.111.111-1", "ana.perez@example.com", "ANA.PEREZ@EXAMPLE.COM")


def gap(reason: str):
    """A duty that is not built yet: strict, so the test fails (XPASS) once the control exists."""
    return pytest.mark.xfail(strict=True, reason=f"GAP: {reason}")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def _pans(text: str) -> list[str]:
    """Card-number-shaped strings: 13-19 digits (spaces or dashes allowed) with a card network's first digit
    (3 Amex/Diners/JCB, 4 Visa, 5 and 2 Mastercard, 6 Discover) that pass the Luhn check."""
    found = []
    for match in re.finditer(r"(?<![\d])(?:\d[ -]?){12,18}\d(?![\d])", text):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and digits[0] in "23456" and _luhn(digits):
            found.append(digits)
    return found


@pytest.fixture
def sqlite_system(tmp_path):
    """Production wiring with SQLite, so the tests can read exactly what is written to disk."""
    path = tmp_path / "compliance.db"
    services, adapters = build(make_settings(persistence="sqlite", sqlite_path=str(path)))
    return services, adapters, path


def _stored_bytes(path: Path) -> str:
    """The database and its write-ahead log (WAL mode keeps recent writes in <db>-wal until a checkpoint)."""
    parts = [path, path.with_name(path.name + "-wal")]
    return "".join(p.read_bytes().decode("utf-8", errors="ignore") for p in parts if p.exists())


# ------------------------------------------------------------------------------------------------
# Built controls
# ------------------------------------------------------------------------------------------------
@needs_pdf
def test_c01_card_numbers_are_kept_as_the_last_four_digits_only(sqlite_system):
    """PCI DSS v4.0 req. 3.3 and 3.4.1 (no full PAN retained or shown); Ley 21.719 art. 3 c) (proportionality).

    Even a statement that prints the full card number is stored with its last four digits only."""
    from tests.statement_samples import CardSample, bice_xlsx, card_pdf

    services, _, path = sqlite_system
    full_pan = "4111 1111 1111 1111"
    assert _pans(full_pan), "the detector must recognize a test PAN"
    for content in (card_pdf(CardSample(card_number=full_pan)), bice_xlsx()):
        result = services.statements.import_statement(USER, content)
        assert result.ok
        for imported in result.data.imports:
            assert re.fullmatch(r"\*{4}\w{4}", imported.statement.account_ref)
    responses = to_primitive([services.statements.list_statements(USER), services.ledger.list_transactions(USER)])
    assert _pans(str(responses)) == []
    assert _pans(_stored_bytes(path)) == []


@needs_pdf
def test_c02_the_holders_identity_printed_on_a_statement_is_not_stored(sqlite_system):
    """Ley 21.719 art. 3 c) (only the data the purpose needs): names, RUT and e-mail are read past, never kept."""
    from tests.statement_samples import card_pdf, santander_pdf, santander_xlsx

    services, adapters, path = sqlite_system
    for content in (santander_pdf(), santander_xlsx(), card_pdf()):
        assert services.statements.import_statement(USER, content).ok
    stored = _stored_bytes(path) + str([e.to_record() for e in adapters.audit_log.events()])
    for identifier in HOLDER_IDENTITY:
        assert identifier not in stored, identifier


@needs_pdf
def test_c03_statement_text_leaves_the_api_only_as_untrusted_data(services):
    """OWASP LLM01 (indirect prompt injection), ASVS 5.0 V1 (output encoding), Ley 19.496 art. 3 b).

    Merchant text a bank printed reaches clients and the model wrapped as {"untrusted_text": ...}, never as
    instructions or markup to render."""
    from tests.statement_samples import card_pdf

    imported = services.statements.import_statement(USER, card_pdf()).data.imports[0].statement
    detail = services.statements.get_statement(USER, imported.statement_id).data
    assert all(set(line.description) == {"untrusted_text"} for line in detail.lines)
    assert all(set(plan.description) == {"untrusted_text"} for plan in imported.obligations.installments)
    for txn in services.ledger.list_transactions(USER).data.transactions:
        assert set(txn.merchant) == {"untrusted_text"}


@needs_pdf
def test_c04_a_user_cannot_reach_another_users_financial_records(services):
    """OWASP API1:2023 (broken object level authorization); Ley 21.719 art. 14 bis (confidentiality).

    Another user's statement id answers exactly like an id that does not exist, so ids cannot be enumerated."""
    from tests.statement_samples import santander_pdf

    client = TestClient(create_app(services))
    upload = client.post("/v1/statements", content=santander_pdf(), headers={"Content-Type": "application/pdf", "X-User-Id": "camila"})
    statement_id = upload.json()["data"]["imports"][0]["statement"]["statement_id"]
    as_diego = {"X-User-Id": "diego"}
    assert client.get("/v1/statements", headers=as_diego).json()["data"] == []
    assert client.get("/v1/transactions", headers=as_diego).json()["data"]["transactions"] == []
    foreign = client.get(f"/v1/statements/{statement_id}", headers=as_diego)
    missing = client.get("/v1/statements/stmt_does_not_exist", headers=as_diego)
    assert foreign.status_code == missing.status_code == 409
    assert foreign.json()["message"] == missing.json()["message"]
    assert all(e["user_id"] == "diego" for e in client.get("/v1/audit", headers=as_diego).json()["events"])


def test_c05_uploads_are_typed_by_content_and_bounded(services):
    """OWASP API4:2023 (resource consumption), ASVS 5.0 V5 (file handling).

    The bytes decide the type, never the Content-Type or a name: HTML sent as a PDF and legacy .xls are refused,
    and the size limit holds with or without a declared length (see also tests/adapters for zip and XML bombs)."""
    client = TestClient(create_app(services))
    html_as_pdf = client.post("/v1/statements", content=b"<html><script>alert(1)</script></html>", headers={"Content-Type": "application/pdf"})
    legacy_xls = client.post("/v1/statements", content=b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)
    assert html_as_pdf.status_code == legacy_xls.status_code == 422
    assert "<script>" not in html_as_pdf.text
    oversized = client.post("/v1/statements", content=b"%PDF", headers={"Content-Length": str(16 * 1024 * 1024)})
    assert oversized.status_code == 413


def test_c06_errors_do_not_leak_internals(services, monkeypatch):
    """ASVS 5.0 V16 (error handling), OWASP API8:2023 (security misconfiguration): no stack trace or path."""

    def explode(*args, **kwargs):
        raise RuntimeError("boom at /home/someone/secret/path.py line 42")

    monkeypatch.setattr(services.ledger, "list_transactions", explode)
    response = TestClient(create_app(services), raise_server_exceptions=False).get("/v1/transactions")
    assert response.status_code == 500
    assert "Traceback" not in response.text and "/home/" not in response.text and "boom" not in response.text


def _tracked_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return out.splitlines()


SECRET_PATTERNS = {
    "Anthropic key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "OpenRouter key": r"sk-or-[A-Za-z0-9_-]{20,}",
    "OpenAI-style key": r"\bsk-[A-Za-z0-9]{32,}",
    "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
    "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{36,}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}


def test_c07_the_public_repository_holds_no_secrets_and_no_real_statements():
    """ASVS 5.0 V13 (secrets), Ley 21.719 arts. 3 h) and 14 bis (confidentiality), SCOPE X5 (public repository)."""
    files = _tracked_files()
    assert not [f for f in files if Path(f).name == ".env" or Path(f).name.startswith(".env.") and not f.endswith(".example")]
    assert not [f for f in files if f.startswith("cartolas/") and not f.endswith((".gitkeep", "README.md"))]
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in ignored and "cartolas" in ignored
    leaks = []
    for name in files:
        path = ROOT / name
        if path.suffix in {".png", ".jpg", ".pdf", ".ico", ".woff", ".woff2", ".xlsx", ".db"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        leaks += [(name, label) for label, pattern in SECRET_PATTERNS.items() if re.search(pattern, text)]
        leaks += [(name, "card number") for pan in _pans(text) if not pan.startswith("4111111111111111")]
    assert leaks == []


def test_c08_sql_is_always_parameterized(tmp_path):
    """ASVS 5.0 V1 (injection), OWASP API8:2023. Statically: no SQL built from strings in the SQLite adapter.
    Dynamically: an injection-shaped user id is just an id."""
    tree = ast.parse((SRC / "adapters/outbound/persistence/sqlite.py").read_text(encoding="utf-8"))
    built = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executemany", "executescript"}
        and node.args
        and isinstance(node.args[0], (ast.JoinedStr, ast.BinOp))
    ]
    assert built == [], f"SQL built from strings at lines {built}"

    from neural_ledger.adapters.outbound.persistence.sqlite import SqliteDatabase, SqliteStatementStore, SqliteTransactionStore

    db = SqliteDatabase(tmp_path / "inj.db")
    hostile = "x' OR '1'='1"
    assert SqliteStatementStore(db).for_user(hostile) == ()
    assert SqliteTransactionStore(db).for_user(hostile) == ()


def test_c09_the_language_model_never_receives_secrets(services, adapters):
    """OWASP LLM02 (sensitive information disclosure) and LLM07 (system prompt leakage): the HMAC secret and API
    keys never reach a prompt, so no reply can repeat them."""
    llm = ScriptedFakeLLM([say("ok")])
    chat_with(services, adapters, llm).handle(SESSION, USER, "How much can I save each month?")
    sent = repr(llm.requests)
    assert llm.requests and make_settings().hmac_secret not in sent and DEV_SECRET not in sent
    assert not any(re.search(pattern, sent) for pattern in SECRET_PATTERNS.values())


@needs_pdf
def test_c10_the_audit_trail_detects_tampering_and_holds_no_identifiers(services, adapters):
    """Ley 21.719 arts. 14 quinquies and 14 sexies (security, and being able to detect and report a breach);
    Ley 21.663 (incident detection); ASVS 5.0 V16 (logging). The trail is hash-chained and records what happened
    without the holder's identity or card numbers."""
    from tests.statement_samples import card_pdf, santander_xlsx

    for content in (card_pdf(), santander_xlsx()):
        services.statements.import_statement(USER, content)
    records = str([e.to_record() for e in adapters.audit_log.events()])
    assert "STATEMENT_IMPORTED" in records and services.audit.verify().ok
    assert not any(identifier in records for identifier in HOLDER_IDENTITY) and _pans(records) == []


def test_c11_chat_input_is_bounded(services, adapters):
    """OWASP LLM10 (unbounded consumption), API4:2023: a message is cut at the limit before any model sees it."""
    from neural_ledger.application.use_cases.chat import MAX_MESSAGE_CHARS

    llm = ScriptedFakeLLM([say("ok")])
    chat_with(services, adapters, llm).handle(SESSION, USER, "a" * (MAX_MESSAGE_CHARS * 5))
    assert llm.requests and "a" * (MAX_MESSAGE_CHARS + 1) not in repr(llm.requests)


def test_c12_consumer_information_is_traceable_and_warnings_are_never_dropped():
    """Ley 19.496 art. 3 b) (truthful, timely information): every number the agent states must be a fact and
    every warning must be mentioned. Evidenced by the existing suite; this test keeps the evidence from vanishing."""
    suite = (Path(__file__).parent / "test_security_suite.py").read_text(encoding="utf-8")
    for name in ("test_s07_model_claims_success_when_execution_failed", "test_s08_explanation_contradicts_engine_output"):
        assert f"def {name}(" in suite


def test_c13_only_redacted_statement_text_is_sent_to_jev(monkeypatch):
    """Ley 21.719 art. 3 c) (only the data the purpose needs), and the transfer of data to a provider abroad that
    categorizing with Jev implies (ADR-032): Jev receives each charge's text after redaction, never a name, RUT,
    e-mail, phone or card number, and never a deposit (income goes by rule)."""
    from neural_ledger.adapters.outbound.classifier.jev import JevTransactionClassifier
    from neural_ledger.bootstrap import container
    from neural_ledger.domain.agent.questions import Judgment
    from tests.statement_samples import santander_xlsx

    sent: list[str] = []

    class RecordingJev:
        name = "jev:recording"

        def judge(self, state, questions):
            sent.append(state)
            return {"category": Judgment("category", "other", (("other", 0.9),), 0.9, self.name)}

    monkeypatch.setitem(container.CLASSIFIERS, "jev", lambda s: JevTransactionClassifier(RecordingJev()))
    services, _ = build(make_settings(classifiers=("jev", "naive_bayes")))
    movements = (
        ("03/09", "O.Gerencia", "0071548293 Transf a JUAN PEREZ", "", -40_000),
        ("03/09", "O.Gerencia", "Transf a 11.111.111-1 MARIA SOTO", "", -25_000),
        ("05/09", "O.Gerencia", "TEF DE PEDRO ROJAS 12.345.678-5", "", 150_000),
        ("09/09", "O.Gerencia", "Aviso maria.soto@mail.cl", "", -1_000),
        ("10/09", "O.Gerencia", "Fono +56 9 8765 4321", "", -2_000),
        ("15/09", "O.Gerencia", "PAGO TARJETA 4555 1234 5678 9012", "", -60_000),
    )
    (imported,) = services.statements.import_statement(USER, santander_xlsx(movements)).data.imports
    assert imported.statement.verified and sent, "the charges must have been categorized by Jev"
    personal = ("JUAN", "PEREZ", "MARIA", "SOTO", "PEDRO", "ROJAS", "ANA", "11.111.111-1", "12.345.678-5", "maria.soto@mail.cl",
                "8765 4321", "4555 1234 5678 9012", "0071548293")  # fmt: skip
    leaks = [(needle, text) for text in sent for needle in personal if needle in text]
    assert leaks == []
    assert not any("TEF DE" in text for text in sent)  # a deposit is income by rule: never sent


# ------------------------------------------------------------------------------------------------
# Gaps: duties not built yet (strict xfail)
# ------------------------------------------------------------------------------------------------
@gap("identity is an X-User-Id header (sandbox); no authentication. OWASP API2:2023, Ley 21.719 art. 14 quinquies")
def test_g01_requests_without_credentials_are_rejected(services):
    response = TestClient(create_app(services)).get("/v1/transactions")
    assert response.status_code == 401


def _routes(services) -> set[tuple[str, str]]:
    return {(method, route.path) for route in create_app(services).routes for method in getattr(route, "methods", ())}


@gap("no export of the user's own data. Ley 21.719 arts. 5 (access) and 9 (portability)")
def test_g02_a_user_can_export_all_of_their_data(services):
    assert ("GET", "/v1/me/export") in _routes(services)


@gap("no deletion of the user's statements and transactions. Ley 21.719 art. 7 (supresión)")
def test_g03_a_user_can_delete_their_data(services):
    assert ("DELETE", "/v1/me/data") in _routes(services)


@gap("no correction of a transaction (ADR-021, ADR-023). Ley 21.719 art. 6 (rectificación)")
def test_g04_a_user_can_correct_their_records(services):
    assert any(method == "PATCH" and path.startswith("/v1/transactions/") for method, path in _routes(services))


@gap("no way to oppose or block processing. Ley 21.719 arts. 8 (oposición) and 8 ter (bloqueo)")
def test_g05_a_user_can_oppose_or_block_processing(services):
    assert ("PUT", "/v1/me/processing") in _routes(services)


@gap("statements are processed without a recorded, purpose-specific consent. Ley 21.719 art. 12")
def test_g06_importing_a_statement_requires_recorded_consent(services):
    response = TestClient(create_app(services)).post("/v1/statements", content=b"%PDF-1.7", headers={"X-User-Id": "nobody"})
    assert response.status_code in (403, 428)


@gap("no rate limiting. OWASP API4:2023, LLM10")
def test_g07_bursts_are_rate_limited(services):
    client = TestClient(create_app(services))
    codes = {client.post("/v1/statements", content=b"x").status_code for _ in range(60)}
    assert 429 in codes


def test_g08_cors_is_not_open_by_default():
    assert "*" not in Settings().cors_origins


def test_g09_responses_carry_security_headers(services):
    headers = TestClient(create_app(services)).get("/v1/transactions").headers
    assert headers.get("x-content-type-options") == "nosniff"
    assert "no-store" in headers.get("cache-control", "")


def test_g10_live_mode_refuses_the_development_secret():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(ValueError, match="NL_HMAC_SECRET"):
            build(make_settings(llm="openrouter", openrouter_api_key="sk-or-test", hmac_secret=DEV_SECRET))


@needs_pdf
@gap("statements are stored in plaintext SQLite. Ley 21.719 art. 14 quinquies (security measures), ASVS 5.0 V14")
def test_g11_financial_records_are_encrypted_at_rest(sqlite_system):
    from tests.statement_samples import santander_xlsx

    services, _, path = sqlite_system
    services.statements.import_statement(USER, santander_xlsx())
    assert "Compra Nacional VD SHOP ONE" not in _stored_bytes(path)


def test_g12_privacy_policy_and_breach_runbook_exist():
    assert (ROOT / "docs/PRIVACY.md").is_file()
    assert (ROOT / "docs/runbooks/INCIDENT_RESPONSE.md").is_file()


# ------------------------------------------------------------------------------------------------
def test_every_compliance_test_is_in_the_security_map():
    """docs/SECURITY.md lists every C and G test with its norm, so the map and the evidence cannot drift."""
    names = re.findall(r"^def (test_[cg]\d{2}_\w+)", Path(__file__).read_text(encoding="utf-8"), flags=re.M)
    security_md = (ROOT / "docs/SECURITY.md").read_text(encoding="utf-8")
    missing = [n for n in names if f"`{n.split('_')[1].upper()}`" not in security_md]
    assert len(names) == 25 and missing == []
