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
    llm: str = "scripted"  # scripted | openrouter | anthropic (deprecated, ADR-027: logs a warning)
    llm_model: str = ""  # empty = the provider's default (DEFAULT_LLM_MODELS)
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None
    decision_chain: tuple[str, ...] = ("rules",)  # e.g. ("jev", "rules")
    typesafe_api_key: str | None = None
    jev_model: str = "jev-1.14-20261014"  # pinned: the jev-latest alias moves when TypeSafe ships a release
    persistence: str = "memory"  # memory | sqlite
    sqlite_path: str = "./var/neural_ledger.db"
    data_key: str | None = None  # G11: 64 hex chars sealing SQLite payloads; offline without it, a key file next to the database
    data_key_file: str | None = None  # a file holding the key, read before NL_DATA_KEY; None = the Docker secret path (data_key.py)
    deployment: str = "local"  # local | deployed: deployed refuses a missing key, a key on the data volume and the dev secret
    clock: str = "system"  # system | fixed (tests and recorded demos)
    fixed_now: str = "2026-10-29T12:00:00-03:00"
    ids: str = "uuid"  # uuid | sequential
    hmac_secret: str = DEV_SECRET
    data_dir: Path | None = None
    contracts_dir: Path | None = None
    # The web app reaches the API through a same-origin proxy (nginx at /api in Docker, the Vite dev proxy),
    # so CORS only matters for a UI served from another origin. "*" only from an explicit NL_CORS_ORIGINS=*.
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    rate_limit: bool = True  # G07: 429 over the per-caller and per-IP budgets in adapters/inbound/http/rate_limit.py
    ocr_model_dir: str | None = None  # EasyOCR weights; None = ~/.EasyOCR/model (scans and photos only)
    classifiers: tuple[str, ...] = ("naive_bayes",)  # spending categories, tried in order, e.g. ("jev", "naive_bayes"); see CLASSIFIERS
    pii_detector: str = "none"  # none | azure: a second layer after the redaction rules; see DETECTORS in container.py
    azure_language_endpoint: str | None = None  # e.g. https://<resource>.cognitiveservices.azure.com
    azure_language_api_key: str | None = None
    auth: str = "demo"  # demo (X-User-Id header, read-only profiles) | accounts (nl_session cookie; docker compose)
    app_origins: tuple[str, ...] = ("http://localhost:3000", "http://localhost:5173")  # may send unsafe requests (accounts)
    cookie_secure: str = "auto"  # auto | true | false: the Secure flag on the session cookie
    demo_personas: bool = True  # accounts mode: allow POST /v1/auth/demo-session for camila and diego
    email_checks: tuple[str, ...] = ("disposable",)  # sign-up email domains, see EMAIL_CHECKS in container.py; dns needs the network
    investments: str = "fixture"  # fixture (synthetic account, offline) | fintual (the provider's API); see INVESTMENT_PROVIDERS (ADR-044)
    fintual_base_url: str = "https://fintual.cl/api"
    fintual_diagnostics: bool = False  # local diagnosis: log the sign-in's shape and probe other token styles (statuses only)
    knowledge_bases: tuple[str, ...] = ("lexical",)  # concept cards (ADR-040), tried in order, e.g. ("chroma", "lexical"); see KNOWLEDGE_BASES
    kb_dir: str = "./var/chroma"  # the Chroma index (embedded mode) and the embedding model's weights
    kb_url: str | None = None  # a Chroma server, e.g. http://chroma:8000 (docker compose --profile rag); None = embedded in kb_dir
    kb_embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    connectors: str = "fixture"  # fixture (synthetic MCP server and bank) | live (real servers the user adds, Fintoc), ADR-047
    connectors_live: bool = False  # NL_DEPLOYMENT=deployed turns live connectors off unless this is true
    mcp_allow_private: bool = False  # local development only: lets an MCP server on http://localhost be added
    fintoc_secret_key: str | None = None
    fintoc_public_key: str | None = None

    @property
    def connectors_mode(self) -> str:
        """off | fixture | live: what /v1/connections reports. A public deployment never reaches real services by default."""
        if self.connectors == "live" and self.deployment == "deployed" and not self.connectors_live:
            return "off"
        return self.connectors

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
        """Live whenever any setting sends data to a provider: the LLM, Jev (decisions or categories), the Azure detector,
        an investment provider (the credentials the user types to link an account), or live connectors (a token to the
        MCP servers users add, Fintoc for the bank). Connectors switched off in a deployment do not count."""
        offline = (
            self.llm == "scripted"
            and all(m == "rules" for m in self.decision_chain)
            and "jev" not in self.classifiers
            and self.pii_detector == "none"
            and self.investments == "fixture"
            and self.connectors_mode != "live"
        )
        return "offline" if offline else "live"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env

        def get(key: str, default: str) -> str:
            value = e.get(key)
            return value if value not in (None, "") else default

        chain = tuple(part.strip() for part in get("NL_DECISION_CHAIN", "rules").split(",") if part.strip())
        classifiers = tuple(part.strip() for part in get("NL_CLASSIFIER", "naive_bayes").split(",") if part.strip())
        knowledge_bases = tuple(part.strip() for part in get("NL_KNOWLEDGE_BASE", "lexical").split(",") if part.strip())
        email_checks = tuple(part.strip() for part in get("NL_EMAIL_CHECKS", "disposable").split(",") if part.strip() not in ("", "none"))
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
            data_key=e.get("NL_DATA_KEY") or None,
            data_key_file=e.get("NL_DATA_KEY_FILE") or None,
            deployment=get("NL_DEPLOYMENT", cls.deployment),
            clock=get("NL_CLOCK", cls.clock),
            fixed_now=get("NL_FIXED_NOW", cls.fixed_now),
            ids=get("NL_IDS", cls.ids),
            hmac_secret=get("NL_HMAC_SECRET", DEV_SECRET),
            data_dir=Path(e["NL_DATA_DIR"]) if e.get("NL_DATA_DIR") else None,
            contracts_dir=Path(e["NL_CONTRACTS_DIR"]) if e.get("NL_CONTRACTS_DIR") else None,
            cors_origins=tuple(o.strip() for o in get("NL_CORS_ORIGINS", "http://localhost:3000").split(",")),
            rate_limit=get("NL_RATE_LIMIT", "on").lower() not in ("off", "false", "0"),
            ocr_model_dir=e.get("NL_OCR_MODEL_DIR") or None,
            classifiers=classifiers or cls.classifiers,
            pii_detector=get("NL_PII_DETECTOR", cls.pii_detector),
            azure_language_endpoint=e.get("AZURE_LANGUAGE_ENDPOINT") or None,
            azure_language_api_key=e.get("AZURE_LANGUAGE_API_KEY") or None,
            auth=get("NL_AUTH", cls.auth),
            app_origins=tuple(o.strip() for o in get("NL_APP_ORIGINS", ",".join(cls.app_origins)).split(",") if o.strip()),
            cookie_secure=get("NL_COOKIE_SECURE", cls.cookie_secure),
            demo_personas=_flag(get("NL_DEMO_PERSONAS", "true"), "NL_DEMO_PERSONAS"),
            email_checks=email_checks,
            investments=get("NL_INVESTMENTS", cls.investments),
            fintual_base_url=get("NL_FINTUAL_BASE_URL", cls.fintual_base_url),
            fintual_diagnostics=_flag(get("NL_FINTUAL_DIAGNOSTICS", "false"), "NL_FINTUAL_DIAGNOSTICS"),
            knowledge_bases=knowledge_bases or cls.knowledge_bases,
            kb_dir=get("NL_KB_DIR", cls.kb_dir),
            kb_url=get("NL_KB_URL", "") or None,
            kb_embedding_model=get("NL_KB_EMBEDDING_MODEL", cls.kb_embedding_model),
            connectors=get("NL_CONNECTORS", cls.connectors),
            connectors_live=_flag(get("NL_CONNECTORS_LIVE", "false"), "NL_CONNECTORS_LIVE"),
            mcp_allow_private=_flag(get("NL_MCP_ALLOW_PRIVATE", "false"), "NL_MCP_ALLOW_PRIVATE"),
            fintoc_secret_key=e.get("FINTOC_SECRET_KEY") or None,
            fintoc_public_key=e.get("FINTOC_PUBLIC_KEY") or None,
        )


def _flag(value: str, name: str) -> bool:
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ValueError(f"{name} must be true or false")
