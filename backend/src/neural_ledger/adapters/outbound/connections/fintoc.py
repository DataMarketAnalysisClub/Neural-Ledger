"""Fintoc's Movements API as a BankFeed (ADR-047): the user's own bank accounts and movements, read-only.

Checked on docs.fintoc.com on 2026-10-19 (API reference v2026-02-01):
- Base https://api.fintoc.com; the secret key goes in the Authorization header as it is (no scheme).
- GET /v1/links/exchange?exchange_token=… returns the link with its accounts; `link_token` is returned only there.
- GET /v1/accounts/{id}/movements?link_token=…&since=YYYY-MM-DD&per_page=300&page=n: `amount` is an integer in the
  currency's smallest unit (CLP has no decimals), negative for outflows; `post_date` is when the bank consolidated
  it; `pending` movements are not consolidated yet. Pages follow `page` until a short page.
- The widget needs a link intent created by the server first; its `widget_token` goes to Fintoc.create.
Not checked (the reference page sits behind Fintoc's dashboard login): the link intent's exact body, assumed to be
POST /v1/link_intents {product: movements, country: cl, holder_type: individual} returning `widget_token`, and
GET /v1/accounts?link_token=… for the current balances. Verify both with a sandbox key before a live demo.

Pending movements are skipped: their amount or date can still change, and a later sync reads them once consolidated.
Errors carry the HTTP status or a short code, never Fintoc's message or any key.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from datetime import date
from typing import Any

from ....application.ports import ConnectorUnavailable
from ....domain.connections.bank import BankAccount, BankMovement
from ....domain.ledger.entities import AccountType

BASE_URL = "https://api.fintoc.com"
USER_AGENT = "neural-ledger/0.1"
PER_PAGE = 300
MAX_PAGES = 40  # 12,000 movements per account per sync
MAX_BYTES = 5_000_000


class FintocBankFeed:
    name = "fintoc"

    def __init__(self, secret_key: str, public_key: str, *, base_url: str = BASE_URL, timeout_s: float = 15.0) -> None:
        if not secret_key or not public_key:
            raise ValueError("FINTOC_SECRET_KEY and FINTOC_PUBLIC_KEY are required for a live bank connection")
        self.public_key: str | None = public_key
        self._secret = secret_key
        self._base = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def start(self) -> str | None:
        intent = self._call("POST", "/v1/link_intents", body={"product": "movements", "country": "cl", "holder_type": "individual"})
        token = intent.get("widget_token") if isinstance(intent, dict) else None
        if not isinstance(token, str) or not token:
            raise ConnectorUnavailable("PROTOCOL")
        return token

    def exchange(self, exchange_token: str) -> str:
        link = self._call("GET", "/v1/links/exchange", {"exchange_token": exchange_token})
        token = link.get("link_token") if isinstance(link, dict) else None
        if not isinstance(token, str) or not token:
            raise ConnectorUnavailable("PROTOCOL")
        return token

    def fetch(self, link_token: str, since: date | None) -> Sequence[tuple[BankAccount, Sequence[BankMovement]]]:
        accounts = self._call("GET", "/v1/accounts", {"link_token": link_token})
        if not isinstance(accounts, list):
            raise ConnectorUnavailable("PROTOCOL")
        out = []
        for raw in accounts:
            account = _account(raw)
            if account is not None:
                out.append((account, self._movements(link_token, account.account_id, since)))
        return out

    def _movements(self, link_token: str, account_id: str, since: date | None) -> list[BankMovement]:
        found: list[BankMovement] = []
        for page in range(1, MAX_PAGES + 1):
            query = {"link_token": link_token, "per_page": str(PER_PAGE), "page": str(page)}
            if since is not None:
                query["since"] = since.isoformat()
            rows = self._call("GET", f"/v1/accounts/{urllib.parse.quote(account_id, safe='')}/movements", query)
            if not isinstance(rows, list):
                raise ConnectorUnavailable("PROTOCOL")
            found.extend(m for m in (_movement(r) for r in rows) if m is not None)
            if len(rows) < PER_PAGE:
                return found
        raise ConnectorUnavailable("TOO_MANY_MOVEMENTS")

    def _call(self, method: str, path: str, query: dict[str, str] | None = None, body: dict[str, Any] | None = None) -> Any:
        url = f"{self._base}{path}" + (f"?{urllib.parse.urlencode(query)}" if query else "")
        headers = {"Authorization": self._secret, "Accept": "application/json", "User-Agent": USER_AGENT}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self._timeout_s) as response:
                raw = response.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise ConnectorUnavailable(f"HTTP_{exc.code}") from None
        except TimeoutError:
            raise ConnectorUnavailable("TIMEOUT") from None
        except (OSError, ValueError):
            raise ConnectorUnavailable("NETWORK") from None
        if len(raw) > MAX_BYTES:
            raise ConnectorUnavailable("TOO_LARGE")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ConnectorUnavailable("PROTOCOL") from None


# shortcut: cards and credit lines are skipped (their balance is a debt, with its own sign and billing); read them
# through card statements (ADR-031) until a card account gets its own reconciliation here.
ACCOUNT_TYPES = {"checking_account": AccountType.CHECKING, "sight_account": AccountType.CHECKING, "savings_account": AccountType.SAVINGS}


def _account(raw: Any) -> BankAccount | None:
    try:
        kind = ACCOUNT_TYPES.get(str(raw.get("type", "")).lower())
        if kind is None:
            return None
        balance = raw["balance"]["current"]
        if isinstance(balance, bool) or not isinstance(balance, int):
            raise TypeError
        return BankAccount(str(raw["id"]), str(raw.get("number") or raw["id"]), str(raw["currency"]).upper(), balance, kind)
    except (KeyError, TypeError, AttributeError):
        raise ConnectorUnavailable("PROTOCOL") from None


def _movement(raw: Any) -> BankMovement | None:
    try:
        if raw.get("pending") is True:
            return None
        amount = raw["amount"]
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError
        posted = date.fromisoformat(str(raw["post_date"])[:10])
        reference = raw.get("reference_id")
        return BankMovement(str(raw["id"]), posted, str(raw.get("description") or ""), amount, str(reference) if reference else None)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ConnectorUnavailable("PROTOCOL") from None
