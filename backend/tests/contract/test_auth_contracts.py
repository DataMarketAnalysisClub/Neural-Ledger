import json

import pytest

from ..conftest import CONTRACTS
from .test_contracts import jsonschema, validate

SCHEMAS = (
    "auth/signup_request.schema.json",
    "auth/signin_request.schema.json",
    "auth/demo_session_request.schema.json",
    "auth/session.schema.json",
    "auth/me.schema.json",
    "auth/error.schema.json",
    "auth/account_deletion_request.schema.json",
    "auth/account_deletion.schema.json",
    "auth/data_export.schema.json",
    "profile/profile_update.schema.json",
)


@pytest.mark.parametrize("relative", SCHEMAS)
def test_schema_examples_validate_under_draft_2020_12(relative: str) -> None:
    schema = json.loads((CONTRACTS / relative).read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    for example in schema["examples"]:
        validate(example, relative)


def test_new_schema_ids_are_distinct() -> None:
    ids = [json.loads((CONTRACTS / relative).read_text(encoding="utf-8"))["$id"] for relative in SCHEMAS]

    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    ("relative", "body"),
    [
        ("auth/signup_request.schema.json", {"email": "ana@accounts.invalid", "password": "tenletters"}),
        ("auth/signup_request.schema.json", {"email": "ana@accounts.invalid", "password": "tenletters", "display_name": "Ana"}),
        ("auth/signup_request.schema.json", {"email": "ana@accounts.invalid", "password": "tenletters", "display_name": "Ana", "sandbox_acknowledged": False}),
        ("auth/signup_request.schema.json", {"email": "ana@accounts.invalid", "password": "short", "display_name": "Ana"}),
        ("auth/signup_request.schema.json", {"email": "ana@accounts.invalid", "password": "x" * 129, "display_name": "Ana"}),
        ("auth/signup_request.schema.json", {"email": "ana@accounts.invalid", "password": "tenletters", "display_name": "Ana", "language": "EN"}),
        ("auth/signup_request.schema.json", {"email": "ana@accounts.invalid", "password": "tenletters", "display_name": "Ana", "declared_tolerance": "aggressive"}),
        ("auth/signin_request.schema.json", {"email": "ana@accounts.invalid"}),
        ("auth/signin_request.schema.json", {"email": "ana@accounts.invalid", "password": "wrong", "otp": "123456"}),
        ("auth/demo_session_request.schema.json", {"persona": "usr_1"}),
        ("auth/demo_session_request.schema.json", {"persona": "camila", "user_id": "diego"}),
        ("auth/session.schema.json", {"user_id": "usr_1", "expires_at": "2026-10-15T12:00:00Z", "token": "secret"}),
        ("auth/session.schema.json", {"user_id": "usr_1", "expires_at": "2026-10-15T12:00:00Z", "email": "ana@accounts.invalid"}),
        ("auth/me.schema.json", {"user_id": "usr_1", "data_source": "unknown", "expires_at": "2026-10-15T12:00:00Z"}),
        ("auth/me.schema.json", {"user_id": "usr_1", "data_source": "empty", "expires_at": "2026-10-15T12:00:00Z", "email": "ana@accounts.invalid"}),
        ("auth/me.schema.json", {"user_id": "usr_1", "data_source": "empty", "expires_at": "2026-10-15T12:00:00Z", "token": "secret"}),
        ("auth/error.schema.json", {"status": "INVALID_CREDENTIALS", "message": "invalid credentials", "email": "ana@accounts.invalid"}),
        ("auth/error.schema.json", {"status": "INVALID_CREDENTIALS", "message": "invalid credentials", "token": "secret"}),
        ("auth/error.schema.json", {"status": "INVALID_INPUT", "message": "invalid input"}),
        ("auth/error.schema.json", {"status": "UNKNOWN", "message": "unknown error"}),
        ("profile/profile_update.schema.json", {}),
        ("profile/profile_update.schema.json", {"display_name": ""}),
        ("profile/profile_update.schema.json", {"display_name": "x" * 41}),
        ("profile/profile_update.schema.json", {"language": "EN"}),
        ("profile/profile_update.schema.json", {"declared_tolerance": "aggressive"}),
        ("profile/profile_update.schema.json", {"language": "en", "questionnaire": []}),
        ("profile/profile_update.schema.json", {"display_name": "Ana", "questionnaire_version": "pq-0.1"}),
    ],
)
def test_invalid_or_extra_fields_are_rejected(relative: str, body: dict[str, str | list[str]]) -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate(body, relative)


def test_signin_strings_do_not_create_a_validation_oracle() -> None:
    for email, password in (("not-an-email", "x"), ("", ""), ("ana@accounts.invalid", "wrong")):
        validate({"email": email, "password": password}, "auth/signin_request.schema.json")


def test_signup_rejects_malformed_email_when_format_is_checked() -> None:
    schema = json.loads((CONTRACTS / "auth/signup_request.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())

    with pytest.raises(jsonschema.ValidationError):
        validator.validate({"email": "not-an-email", "password": "tenletters", "display_name": "Ana", "sandbox_acknowledged": True})


def test_auth_error_http_status_annotation_matches_public_mapping() -> None:
    schema = json.loads((CONTRACTS / "auth/error.schema.json").read_text(encoding="utf-8"))
    expected = {
        "IDENTITY_HEADER_REJECTED": 400,
        "UNAUTHENTICATED": 401,
        "INVALID_CREDENTIALS": 401,
        "ORIGIN_REJECTED": 403,
        "PROFILE_READ_ONLY": 403,
        "NOT_FOUND": 404,
        "EMAIL_TAKEN": 409,
        "INVALID_INPUT": 422,
    }

    assert schema["x-http-status"] == expected
    assert set(schema["properties"]["status"]["enum"]) == set(expected)
    assert "x-http-status" not in schema["properties"]


def test_error_examples_never_echo_credentials() -> None:
    examples = json.loads((CONTRACTS / "auth/error.schema.json").read_text(encoding="utf-8"))["examples"]

    for example in examples:
        assert not {"email", "password", "token"} & example.keys()
        assert "@" not in example["message"]
        assert "example-passphrase" not in example["message"]
