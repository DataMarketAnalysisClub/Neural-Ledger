"""Settings from environment variables (see .env.example). Defaults = offline demo mode."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEV_SECRET = "dev-only-insecure-secret-change-me"
DEFAULT_LLM_MODELS = {"anthropic": "claude-sonnet-5-5", "openrouter": "anthropic/claude-haiku-5.5"}


def _find_dir(name: str) -> Path:
    """Look for <name>/ upwards from the working directory and from this file (repo layout)."""
    starts = [Path.cwd(), Path(__file__).resolve()]
    for start in starts:
        for folder in [start, *start.parents]:
            candidate = folder / name
            if candidate.is_dir():
                return candidate
    return Path(name)


@dataclass(frozen=True)
class Settings:
    persona: str = "camila"
    model_source: str = "fixture"  # fixture (calibrated personas) | ledger (data/ledgers + stage-1 estimators)
    llm: str = "scripted"  # scripted | anthropic | openrouter
    llm_model: str = ""  # empty = the provider's default (DEFAULT_LLM_MODELS)
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None
    decision_chain: tuple[str, ...] = ("rules",)  # e.g. ("jev", "rules")
    typesafe_api_key: str | None = None
    jev_model: str = "jev-1.13.0"  # pinned: the jev-latest alias moves when TypeSafe ships a release
    persistence: str = "memory"  # memory | sqlite
    sqlite_path: str = "./var/neural_ledger.db"
    clock: str = "system"  # system | fixed (tests and recorded demos)
    fixed_now: str = "2026-10-29T12:00:00-03:00"
    ids: str = "uuid"  # uuid | sequential
    hmac_secret: str = DEV_SECRET
    data_dir: Path | None = None
    contracts_dir: Path | None = None
    cors_origins: tuple[str, ...] = ("*",)
    ocr_model_dir: str | None = None  # EasyOCR weights; None = ~/.EasyOCR/model (scans and photos only)
    classifiers: tuple[str, ...] = ("naive_bayes",)  # spending categories, tried in order, e.g. ("jev", "naive_bayes"); see CLASSIFIERS
    pii_detector: str = "none"  # none | azure: a second layer after the redaction rules; see DETECTORS in container.py
    azure_language_endpoint: str | None = None  # e.g. https://<resource>.cognitiveservices.azure.com
    azure_language_api_key: str | None = None

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir or _find_dir("data")

    @property
    def resolved_contracts_dir(self) -> Path:
        return self.contracts_dir or _find_dir("contracts")

    @property
    def resolved_llm_model(self) -> str:
        return self.llm_model or DEFAULT_LLM_MODELS.get(self.llm, "")

    @property
    def fixed_instant(self) -> datetime:
        return datetime.fromisoformat(self.fixed_now)

    @property
    def mode(self) -> str:
        offline = self.llm == "scripted" and all(m == "rules" for m in self.decision_chain) and "jev" not in self.classifiers
        return "offline" if offline else "live"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env

        def get(key: str, default: str) -> str:
            value = e.get(key)
            return value if value not in (None, "") else default

        chain = tuple(part.strip() for part in get("NL_DECISION_CHAIN", "rules").split(",") if part.strip())
        classifiers = tuple(part.strip() for part in get("NL_CLASSIFIER", "naive_bayes").split(",") if part.strip())
        return cls(
            persona=get("NL_PERSONA", cls.persona),
            model_source=get("NL_MODEL_SOURCE", cls.model_source),
            llm=get("NL_LLM", cls.llm),
            llm_model=get("NL_LLM_MODEL", cls.llm_model),
            anthropic_api_key=e.get("ANTHROPIC_API_KEY") or None,
            openrouter_api_key=e.get("OPENROUTER_API_KEY") or None,
            decision_chain=chain or ("rules",),
            typesafe_api_key=e.get("TYPESAFE_API_KEY") or None,
            jev_model=get("NL_JEV_MODEL", cls.jev_model),
            persistence=get("NL_PERSISTENCE", cls.persistence),
            sqlite_path=get("NL_SQLITE_PATH", cls.sqlite_path),
            clock=get("NL_CLOCK", cls.clock),
            fixed_now=get("NL_FIXED_NOW", cls.fixed_now),
            ids=get("NL_IDS", cls.ids),
            hmac_secret=get("NL_HMAC_SECRET", DEV_SECRET),
            data_dir=Path(e["NL_DATA_DIR"]) if e.get("NL_DATA_DIR") else None,
            contracts_dir=Path(e["NL_CONTRACTS_DIR"]) if e.get("NL_CONTRACTS_DIR") else None,
            cors_origins=tuple(o.strip() for o in get("NL_CORS_ORIGINS", "*").split(",")),
            ocr_model_dir=e.get("NL_OCR_MODEL_DIR") or None,
            classifiers=classifiers or cls.classifiers,
            pii_detector=get("NL_PII_DETECTOR", cls.pii_detector),
            azure_language_endpoint=e.get("AZURE_LANGUAGE_ENDPOINT") or None,
            azure_language_api_key=e.get("AZURE_LANGUAGE_API_KEY") or None,
        )
