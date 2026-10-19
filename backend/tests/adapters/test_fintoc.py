"""Fintoc's Movements API adapter against a local fake (ADR-047): no network, no key. Every account and movement is invented."""

from __future__ import annotations

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from neural_ledger.adapters.outbound.connections.fintoc import PER_PAGE, FintocBankFeed
from neural_ledger.application.ports import BankFeed, ConnectorUnavailable
from neural_ledger.domain.ledger.entities import AccountType

SECRET = "sk_test_not_a_real_key"
LINK = "link_tok_test"
ACCOUNTS = [
    {"id": "acc_1", "type": "checking_account", "number": "0-000-00-12345-6", "currency": "CLP", "balance": {"available": 500_000, "current": 500_000}},
    {"id": "acc_2", "type": "credit_card", "number": "4555", "currency": "CLP", "balance": {"available": 0, "current": -90_000}},
]


def movement(i: int, pending: bool = False) -> dict:
    return {"id": f"mov_{i}", "amount": -1_000 * (i + 1), "currency": "CLP", "description": f"COMPRA {i}", "post_date": f"2026-10-{1 + i % 28:02d}T00:00:00Z", "pending": pending, "reference_id": None}


class FakeFintoc:
    def __init__(self, movements: list[dict], status: int = 200) -> None:
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self, payload: object, code: int = 200) -> None:
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802 (http.server API)
                url = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                outer.requests.append({"method": "GET", "path": url.path, "query": query, "auth": self.headers.get("Authorization")})
                if status != 200:
                    return self._answer({"error": {"message": "the key sk_live_xxx is invalid"}}, status)
                if url.path == "/v1/links/exchange":
                    return self._answer({"id": "link_1", "link_token": LINK, "accounts": ACCOUNTS})
                if url.path == "/v1/accounts":
                    return self._answer(ACCOUNTS)
                page, per = int(query.get("page", 1)), int(query["per_page"])
                return self._answer(movements[(page - 1) * per : page * per])

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                outer.requests.append({"method": "POST", "path": self.path, "body": body, "auth": self.headers.get("Authorization")})
                return self._answer({"id": "li_1", "widget_token": "li_1_sec_test"})

            def log_message(self, *_):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def fake():
    server = FakeFintoc([movement(0), movement(1, pending=True), movement(2)])
    yield server
    server.close()


def feed(server: FakeFintoc) -> FintocBankFeed:
    return FintocBankFeed(SECRET, "pk_test", base_url=server.url, timeout_s=5)


def test_it_is_a_bank_feed(fake):
    assert isinstance(feed(fake), BankFeed)


def test_start_exchange_and_the_secret_key_header(fake):
    f = feed(fake)
    assert f.start() == "li_1_sec_test"
    assert f.exchange("exch_1") == LINK
    assert fake.requests[0]["body"] == {"product": "movements", "country": "cl", "holder_type": "individual"}
    assert fake.requests[1]["query"] == {"exchange_token": "exch_1"}
    assert all(r["auth"] == SECRET for r in fake.requests)


def test_fetch_skips_cards_and_pending_movements(fake):
    [(account, movements)] = feed(fake).fetch(LINK, date(2026, 9, 1))
    assert (account.account_id, account.balance, account.account_type) == ("acc_1", 500_000, AccountType.CHECKING)
    assert [m.movement_id for m in movements] == ["mov_0", "mov_2"]
    assert movements[0].amount == -1_000 and movements[0].posted_on == date(2026, 10, 1)
    query = fake.requests[-1]["query"]
    assert query["since"] == "2026-09-01" and query["link_token"] == LINK and query["per_page"] == str(PER_PAGE)


def test_fetch_follows_pages_until_a_short_one():
    server = FakeFintoc([movement(i) for i in range(PER_PAGE + 5)])
    try:
        [(_, movements)] = feed(server).fetch(LINK, None)
        assert len(movements) == PER_PAGE + 5
        assert [r["query"].get("page") for r in server.requests if r["path"].endswith("/movements")] == ["1", "2"]
    finally:
        server.close()


def test_errors_carry_the_status_never_fintocs_message():
    server = FakeFintoc([], status=401)
    try:
        with pytest.raises(ConnectorUnavailable) as raised:
            feed(server).exchange("exch_1")
        assert raised.value.args == ("HTTP_401",)
        assert "sk_" not in str(raised.value)
    finally:
        server.close()


def test_keys_are_required():
    with pytest.raises(ValueError):
        FintocBankFeed("", "pk_test")
