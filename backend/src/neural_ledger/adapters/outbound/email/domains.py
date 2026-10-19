"""Sign-up email domain checks (EmailDomainCheck). No domain list is kept here: both come from maintained libraries.

disposable: the community blocklist in disposable-email-domains (yopmail, temp-mail, mailinator, guerrillamail, ...),
offline, matching the domain and every parent domain. dns: email-validator asks DNS whether the domain exists and
receives mail (MX, else A/AAAA, and no null MX). It fails open: a timeout or unreachable resolver lets the email through,
so a sign-up never depends on the network being up.
"""

from __future__ import annotations

DISPOSABLE = "use a permanent email address, not a disposable one"
NO_MAIL = "this email's domain does not receive mail"
INVALID = "use a valid email address"


def _domain(email: str) -> str:
    return email.rpartition("@")[2]


class DisposableEmailBlocklist:
    def __init__(self) -> None:
        try:
            from disposable_email_domains import blocklist
        except ImportError as exc:
            raise RuntimeError("NL_EMAIL_CHECKS=disposable needs the `disposable-email-domains` package (api extra)") from exc
        self._blocklist: frozenset[str] = frozenset(blocklist)

    def refusal(self, email: str) -> str | None:
        labels = _domain(email).split(".")
        # sub.yopmail.com is refused like yopmail.com; the bare TLD is never on the list.
        return DISPOSABLE if any(".".join(labels[i:]) in self._blocklist for i in range(len(labels) - 1)) else None


class DnsEmailDomainCheck:
    def __init__(self, timeout_seconds: int = 3) -> None:
        try:
            import email_validator
        except ImportError as exc:
            raise RuntimeError("NL_EMAIL_CHECKS=dns needs the `email-validator` package (api extra)") from exc
        self._validator = email_validator
        self._timeout = timeout_seconds

    def refusal(self, email: str) -> str | None:
        v = self._validator
        try:
            v.validate_email(email, check_deliverability=True, timeout=self._timeout)
        except v.EmailUndeliverableError:
            return NO_MAIL
        except v.EmailNotValidError:
            return INVALID  # stricter than the domain's syntax check, e.g. a reserved name such as .invalid or .test
        return None
