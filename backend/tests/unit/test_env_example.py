import ast
from pathlib import Path

from neural_ledger.bootstrap.config import Settings
from neural_ledger.bootstrap.container import build

ROOT = Path(__file__).resolve().parents[3]


def test_env_example_covers_every_config_read_and_boots_offline():
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    env = dict(line.split("=", 1) for line in template.splitlines() if line and not line.startswith("#"))
    tree = ast.parse((ROOT / "backend/src/neural_ledger/bootstrap/config.py").read_text(encoding="utf-8"))
    settings_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Settings")
    from_env = next(node for node in settings_class.body if isinstance(node, ast.FunctionDef) and node.name == "from_env")
    keys = {
        node.value for call in ast.walk(from_env) if isinstance(call, ast.Call)
        for node in call.args[:1] if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value.startswith(("NL_", "ANTHROPIC_", "OPENROUTER_", "TYPESAFE_"))
    }
    keys.update(node.value for node in ast.walk(from_env) if isinstance(node, ast.Constant)
                and isinstance(node.value, str) and node.value.startswith("NL_") and node.value in ("NL_DATA_DIR", "NL_CONTRACTS_DIR"))
    assert set(env) == keys
    assert all(not env[key] for key in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "TYPESAFE_API_KEY", "NL_HMAC_SECRET"))
    settings = Settings.from_env(env)
    assert settings.mode == "offline" and settings.model_source == "fixture"
    services, _ = build(settings)
    assert services.mode == "offline"
