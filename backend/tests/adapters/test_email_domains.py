"""Sign-up email domain checks: the disposable blocklist (offline), the DNS check (resolver faked) and the use case."""

import email_validator
import pytest

from neural_ledger.adapters.outbound.email.domains import DISPOSABLE, NO_MAIL, DisposableEmailBlocklist, DnsEmailDomainCheck
from neural_ledger.adapters.outbound.persistence.memory import InMemoryAccountWrites
from neural_ledger.adapters.outbound.system.ids import SequentialIds
from neural_ledger.application.use_cases.accounts import AccountStatus, AccountUseCases
from neural_ledger.bootstrap.container import _email_checks
from tests.application.test_accounts import PASSWORD, World


@pytest.mark.parametrize("email", ["ana@yopmail.com", "ana@temp-mail.org", "ana@mailinator.com", "ana@inbox.yopmail.com"])
def test_disposable_inboxes_are_refused(email):
    assert DisposableEmailBlocklist().refusal(email) == DISPOSABLE


@pytest.mark.parametrize("email", ["ana@gmail.com", "ana@uc.cl", "ana@example.com"])
def test_permanent_domains_pass_the_blocklist(email):
    assert DisposableEmailBlocklist().refusal(email) is None


def test_dns_refuses_a_domain_that_takes_no_mail_and_fails_open_otherwise(monkeypatch):
    calls = []

    def fake(email, **kwargs):
        calls.append(kwargs)
        if email.endswith("@nomail.example"):
            raise email_validator.EmailUndeliverableError("no MX")
        return None  # a timeout also lands here: email-validator reports unknown deliverability, it does not raise

    monkeypatch.setattr(email_validator, "validate_email", fake)
    check = DnsEmailDomainCheck(timeout_seconds=2)
    assert check.refusal("ana@nomail.example") == NO_MAIL
    assert check.refusal("ana@gmail.com") is None
    assert calls[0] == {"check_deliverability": True, "timeout": 2}


class Refuse:
    def refusal(self, email):
        return "nope" if email.endswith("@yopmail.com") else None


def test_signup_refused_by_a_check_stores_nothing():
    w = World()
    w.use_cases = AccountUseCases(
        w.accounts, w.sessions, InMemoryAccountWrites(w.accounts, w.sessions, w.profiles, w.audit),
        w.hasher, w.tokens, w.clock, SequentialIds(), email_checks=[Refuse()],
    )
    refused = w.use_cases.signup("Ana@YOPmail.com", PASSWORD, "Ana")  # checks see the normalized email
    assert (refused.status, refused.field, refused.message) == (AccountStatus.INVALID_INPUT, "email", "nope")
    assert refused.session is None and not w.audit.events() and w.hasher.hashed == []
    assert w.use_cases.signup("ana@example.com", PASSWORD, "Ana").ok


def test_unknown_check_name_is_a_startup_error():
    assert _email_checks(()) == []
    with pytest.raises(ValueError, match="NL_EMAIL_CHECKS"):
        _email_checks(("disposable", "smtp"))
