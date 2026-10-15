"""The Azure AI Language detector against a local fake server: no network, no key (ADR-028).

The fake answers the way REST API 2026-05-01 documents it: for each document, every occurrence of a few known strings
comes back as an entity with an offset in Unicode code points (the stringIndexType the adapter asks for). Every name
and number is fictional.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from neural_ledger.adapters.outbound.privacy import azure_language
from neural_ledger.adapters.outbound.privacy.azure_language import API_VERSION, CATEGORIES, AzureLanguageDetector
from neural_ledger.application.ports import DetectorUnavailable, PersonalDataDetector
from neural_ledger.bootstrap.config import Settings
from neural_ledger.bootstrap.container import DETECTORS, build
from neural_ledger.domain.privacy.redaction import Placeholder, Span
from tests.conftest import make_settings

SECRET = "test_secret_value_not_a_real_key"
KNOWN = {
    "JUAN PEREZ": "Person",
    "MARIA SOTO": "Person",
    "maria.soto@mail.cl": "Email",
    "Av. Siempre Viva 742": "Address",
    "11.111.111-1": "CLIdentityCardNumber",
    "4555 1234 5678 9012": "CreditCardNumber",
    "JUMBO": "Organization",  # never requested: a real service would not send it, and if it did it is ignored
}

Answer = Callable[[dict], tuple[int, object, dict[str, str]]]


def azure_like(body: dict) -> tuple[int, object, dict[str, str]]:
    documents = []
    for document in body["analysisInput"]["documents"]:
        entities = []
        for needle, category in KNOWN.items():
            start = document["text"].find(needle)
            while start != -1:
                entities.append({"text": needle, "category": category, "offset": start, "length": len(needle), "confidenceScore": 0.93})
                start = document["text"].find(needle, start + 1)
        documents.append({"id": document["id"], "redactedText": "*", "entities": entities, "warnings": []})
    return 200, {"kind": "PiiEntityRecognitionResults", "results": {"documents": documents, "errors": [], "modelVersion": "2026-05-01"}}, {}


class FakeAzure:
    """Answers each request with `answer(body)` and records what it received."""

    def __init__(self, answer: Answer = azure_like) -> None:
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 (http.server API)
                url = urlsplit(self.path)
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw)
                outer.requests.append(
                    {"path": url.path, "query": parse_qs(url.query), "headers": dict(self.headers), "body": body, "bytes": len(raw)}
                )
                status, payload, headers = answer(body)
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):  # keep test output clean
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self._server.server_port}/"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def serve():
    servers: list[FakeAzure] = []

    def start(answer: Answer = azure_like) -> FakeAzure:
        server = FakeAzure(answer)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def detector(server: FakeAzure) -> AzureLanguageDetector:
    return AzureLanguageDetector(server.endpoint, SECRET, timeout_s=5)


def fixed(status: int, payload: object, headers: dict[str, str] | None = None) -> Answer:
    return lambda body: (status, payload, headers or {})


# ---- the request ----------------------------------------------------------------------------


def test_the_request_follows_the_documented_api(serve):
    server = serve()
    detector(server).detect(["Transf a JUAN PEREZ"])
    (sent,) = server.requests
    assert sent["path"] == "/language/:analyze-text" and sent["query"] == {"api-version": [API_VERSION]} and API_VERSION == "2026-05-01"
    assert sent["headers"]["Ocp-Apim-Subscription-Key"] == SECRET
    assert sent["headers"]["Content-Type"] == "application/json" and sent["headers"]["User-Agent"].startswith("neural-ledger")
    body = sent["body"]
    assert body["kind"] == "PiiEntityRecognition"
    assert body["parameters"] == {
        "modelVersion": "latest",
        "loggingOptOut": True,  # the default is false in 2026-05-01: never rely on it
        "piiCategories": [
            "Person", "PhoneNumber", "Email", "Address", "BankAccountNumber", "CreditCardNumber",
            "InternationalBankingAccountNumber", "CLIdentityCardNumber",
        ],
        "stringIndexType": "UnicodeCodePoint",
    }  # fmt: skip
    assert "Organization" not in body["parameters"]["piiCategories"]  # it would mask merchants
    assert body["analysisInput"]["documents"] == [{"id": "1", "language": "es", "text": "Transf a JUAN PEREZ"}]


def test_the_detector_is_a_personal_data_detector_and_needs_its_endpoint_and_key():
    assert isinstance(AzureLanguageDetector("https://x.cognitiveservices.azure.com", SECRET), PersonalDataDetector)
    assert AzureLanguageDetector("https://x.cognitiveservices.azure.com", SECRET).name == "azure_language"
    for endpoint, key in (("", SECRET), ("https://x.cognitiveservices.azure.com", "")):
        with pytest.raises(ValueError, match="AZURE_LANGUAGE_ENDPOINT and AZURE_LANGUAGE_API_KEY"):
            AzureLanguageDetector(endpoint, key)


def test_no_text_means_no_request(serve):
    server = serve()
    assert detector(server).detect([]) == ()
    assert detector(server).detect(["", ""]) == ((), ())
    assert server.requests == []


# ---- the answer -------------------------------------------------------------------------------


def test_entities_map_back_to_their_line_and_category(serve):
    server = serve()
    texts = [
        "Compra Nacional MD JUMBO",
        "Transf a JUAN PEREZ 11.111.111-1",
        "",
        "Aviso maria.soto@mail.cl, Av. Siempre Viva 742",
        "PAGO TARJETA 4555 1234 5678 9012",
    ]
    found = detector(server).detect(texts)
    assert found == (
        (),  # JUMBO came back as Organization, which was not asked for: ignored
        (Span(9, 19, Placeholder.PERSON), Span(20, 32, Placeholder.ID)),
        (),
        (Span(6, 24, Placeholder.EMAIL), Span(26, 46, Placeholder.ADDRESS)),
        (Span(13, 32, Placeholder.NUMBER),),
    )
    (sent,) = server.requests  # one document, one line per row
    assert sent["body"]["analysisInput"]["documents"][0]["text"] == "\n".join(text for text in texts if text)


def test_every_requested_category_has_a_placeholder():
    assert set(CATEGORIES.values()) <= set(Placeholder)
    assert CATEGORIES["Person"] is Placeholder.PERSON and CATEGORIES["CLIdentityCardNumber"] is Placeholder.ID


def test_an_entity_across_two_lines_becomes_one_span_on_each(serve):
    def across(body):  # "JUAN\nPEREZ": the end of line one, the row break and the start of line two
        return (
            200,
            {"results": {"documents": [{"id": "1", "entities": [{"category": "Person", "offset": 7, "length": 10}]}], "errors": []}},
            {},
        )

    found = detector(serve(across)).detect(["PAGO A JUAN", "PEREZ GOMEZ"])
    assert found == ((Span(7, 11, Placeholder.PERSON),), (Span(0, 5, Placeholder.PERSON),))


def test_batches_stay_within_the_service_limits(serve):
    server = serve()
    texts = [f"Transf a JUAN PEREZ {i:04d} " + "x" * 1_000 for i in range(40)]
    found = detector(server).detect(texts)
    assert found == tuple((Span(9, 19, Placeholder.PERSON),) for _ in texts)
    assert len(server.requests) > 1
    for sent in server.requests:
        documents = sent["body"]["analysisInput"]["documents"]
        assert 1 <= len(documents) <= azure_language.MAX_DOCUMENTS == 5
        assert all(len(d["text"]) <= azure_language.MAX_DOCUMENT_CHARS == 5_120 for d in documents)
        assert sent["bytes"] <= azure_language.MAX_REQUEST_BYTES == 1_000_000
    sent_lines = [row for sent in server.requests for d in sent["body"]["analysisInput"]["documents"] for row in d["text"].split("\n")]
    assert sent_lines == texts  # every line once, in order


def test_a_line_longer_than_a_document_is_cut_and_still_mapped(serve):
    server = serve()
    text = "x" * 6_000 + " JUAN PEREZ"
    assert detector(server).detect([text]) == ((Span(6_001, 6_011, Placeholder.PERSON),),)
    documents = [d for sent in server.requests for d in sent["body"]["analysisInput"]["documents"]]
    assert [len(d["text"]) for d in documents] == [5_120, 891]


# ---- every error is "unavailable", and never quotes the text or the key ------------------------------

QUOTING = "Invalid document: Transf a JUAN PEREZ"


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (fixed(401, {"error": {"code": "401", "message": "Access denied for " + QUOTING}}), "HTTP 401 (401)"),
        (
            fixed(400, {"error": {"code": "InvalidArgument", "message": QUOTING, "innererror": {"code": "InvalidDocument"}}}),
            "HTTP 400 (InvalidArgument, InvalidDocument)",
        ),
        (
            fixed(429, {"error": {"code": "TooManyRequests", "message": "Rate limit"}}, {"x-ms-error-code": "TooManyRequests"}),
            "HTTP 429 (TooManyRequests)",
        ),
        (fixed(500, b"<html>" + QUOTING.encode() + b"</html>"), "HTTP 500"),
        (fixed(503, {"error": {"code": "ServiceUnavailable", "message": QUOTING}}), "HTTP 503 (ServiceUnavailable)"),
        (
            fixed(200, {"results": {"documents": [], "errors": [{"id": "1", "error": {"code": "InvalidArgument", "message": QUOTING}}]}}),
            "1 document(s) (InvalidArgument)",
        ),
        (fixed(200, b"not json " + QUOTING.encode()), "request failed (JSONDecodeError)"),
        (fixed(200, {"kind": "PiiEntityRecognitionResults"}), "unexpected answer (KeyError)"),
        (
            fixed(200, {"results": {"documents": [{"id": "1", "entities": [{"category": "Person", "offset": 18, "length": 50}]}]}}),
            "unexpected answer",
        ),
        (fixed(200, {"results": {"documents": [{"id": "7", "entities": []}], "errors": []}}), "unexpected answer (KeyError)"),
        (fixed(200, ["not", "an", "object"]), "unexpected answer (TypeError)"),
    ],
)
def test_every_error_raises_unavailable_without_quoting_the_text_or_the_key(serve, answer, reason):
    with pytest.raises(DetectorUnavailable) as caught:
        detector(serve(answer)).detect(["Transf a JUAN PEREZ"])
    message = str(caught.value)
    assert reason in message and message.startswith("azure_language")
    assert "JUAN" not in message and "Transf" not in message and SECRET not in message


def test_an_unreachable_service_is_unavailable(serve):
    server = serve()
    unreachable = detector(server)
    server.close()
    with pytest.raises(DetectorUnavailable, match="request failed"):
        unreachable.detect(["Transf a JUAN PEREZ"])


# ---- wiring: NL_PII_DETECTOR ------------------------------------------------------------------------


def test_settings_read_the_detector_and_its_azure_resource():
    settings = Settings.from_env(
        {"NL_PII_DETECTOR": "azure", "AZURE_LANGUAGE_ENDPOINT": "https://x.example", "AZURE_LANGUAGE_API_KEY": SECRET}
    )
    assert (settings.pii_detector, settings.azure_language_endpoint, settings.azure_language_api_key) == (
        "azure",
        "https://x.example",
        SECRET,
    )
    assert Settings.from_env({}).pii_detector == "none" and sorted(DETECTORS) == ["azure", "none"]


def test_the_default_is_rules_only_and_health_says_so():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from neural_ledger.adapters.inbound.http.app import create_app

    services, _ = build(make_settings())
    assert services.pii_detector == "none"
    assert TestClient(create_app(services)).get("/health").json()["pii_detector"] == "none"


def test_a_missing_key_or_an_unknown_detector_fails_loudly_at_startup():
    with pytest.raises(ValueError, match="AZURE_LANGUAGE_API_KEY"):
        build(make_settings(pii_detector="azure", azure_language_endpoint="https://x.example"))
    with pytest.raises(ValueError, match="NL_PII_DETECTOR"):
        build(make_settings(pii_detector="magic"))


def _cartola():
    pytest.importorskip("pymupdf")
    pytest.importorskip("pdfplumber")
    from tests.statement_samples import Sample, santander_pdf

    # "PAGO A MARIA SOTO" has no transfer keyword: the rules keep the name, only a detector can find it.
    movements = (("02/12", "", "90", "PAGO A MARIA SOTO", -5_000), ("04/12", "", "90", "0000000003 Transf a JUAN PEREZ", -40_000))
    return santander_pdf(Sample(movements=movements, period=("30/11/2025", "31/12/2025")))


def test_with_azure_on_an_import_masks_what_only_the_detector_finds(serve):
    server = serve()
    services, _ = build(make_settings(pii_detector="azure", azure_language_endpoint=server.endpoint, azure_language_api_key=SECRET))
    assert services.pii_detector == "azure_language"
    result = services.statements.import_statement("camila", _cartola())
    assert result.data.imports[0].redaction.detector == "azure_language" and result.data.imports[0].redaction.degraded is False
    detail = services.statements.get_statement("camila", result.data.imports[0].statement.statement_id).data
    assert [line.description["untrusted_text"] for line in detail.lines] == ["PAGO A [PERSON]", "[NUMBER] Transf a [PERSON]"]
    sent = server.requests[0]["body"]["analysisInput"]["documents"][0]["text"]
    assert "MARIA SOTO" in sent  # the trade-off: with Azure on, the raw line leaves the process (docs/SECURITY.md)


def test_with_azure_down_the_import_is_degraded_and_the_rules_still_mask(serve):
    server = serve(fixed(503, {"error": {"code": "ServiceUnavailable", "message": "down"}}))
    services, _ = build(make_settings(pii_detector="azure", azure_language_endpoint=server.endpoint, azure_language_api_key=SECRET))
    result = services.statements.import_statement("camila", _cartola())
    assert result.status.value == "OK" and result.data.imports[0].redaction.degraded is True
    assert "REDACTION_DEGRADED" in [w.code for w in result.warnings]
    detail = services.statements.get_statement("camila", result.data.imports[0].statement.statement_id).data
    assert [line.description["untrusted_text"] for line in detail.lines] == ["PAGO A MARIA SOTO", "[NUMBER] Transf a [PERSON]"]
