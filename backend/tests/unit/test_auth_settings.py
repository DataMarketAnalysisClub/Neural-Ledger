"""NL_AUTH and its companions: demo stays the code default; accounts needs exact app origins."""

from __future__ import annotations

import pytest

from neural_ledger.bootstrap.config import Settings
from neural_ledger.bootstrap.container import build
from tests.conftest import make_settings


def test_defaults_keep_the_offline_demo_identity():
    settings = Settings.from_env({})
    assert settings.auth == "demo"
    assert settings.app_origins == ("http://localhost:3000", "http://localhost:5173")
    assert settings.cookie_secure == "auto" and settings.demo_personas is True
    services, _ = build(make_settings())
    assert services.auth.mode == "demo" and services.accounts is None and services.profile_editing is None


def test_accounts_settings_are_read_from_the_environment():
    settings = Settings.from_env({
        "NL_AUTH": "accounts",
        "NL_APP_ORIGINS": " https://ledger.example , http://localhost:3000,",
        "NL_COOKIE_SECURE": "true",
        "NL_DEMO_PERSONAS": "false",
    })
    assert settings.auth == "accounts"
    assert settings.app_origins == ("https://ledger.example", "http://localhost:3000")
    assert settings.cookie_secure == "true" and settings.demo_personas is False


@pytest.mark.parametrize("value,expected", [("true", True), ("1", True), ("YES", True), ("false", False), ("0", False), ("no", False)])
def test_demo_personas_flag(value, expected):
    assert Settings.from_env({"NL_DEMO_PERSONAS": value}).demo_personas is expected


def test_a_malformed_flag_is_rejected_without_echo():
    with pytest.raises(ValueError) as error:
        Settings.from_env({"NL_DEMO_PERSONAS": "synthetic-value-xyz"})
    assert "synthetic-value-xyz" not in str(error.value)


@pytest.mark.parametrize("overrides", [
    {"auth": "cookies"},
    {"auth": "accounts", "cookie_secure": "sometimes"},
    {"cookie_secure": "maybe"},
    {"auth": "accounts", "app_origins": ()},
    {"auth": "accounts", "app_origins": ("*",)},
    {"auth": "accounts", "app_origins": ("null",)},
    {"auth": "accounts", "app_origins": ("localhost:3000",)},
    {"auth": "accounts", "app_origins": ("http://localhost:3000", "*")},
])
def test_build_rejects_unknown_modes_and_wildcard_origins(overrides):
    with pytest.raises(ValueError):
        build(make_settings(**overrides))


def test_accounts_build_reports_the_enabled_personas():
    services, _ = build(make_settings(auth="accounts", app_origins=("https://ledger.example",), cookie_secure="true"))
    assert services.auth.mode == "accounts" and services.auth.accounts
    assert services.auth.app_origins == ("https://ledger.example",) and services.auth.cookie_secure == "true"
    assert services.auth.demo_personas == ("camila", "diego")
    assert services.accounts is not None and services.profile_editing is not None
