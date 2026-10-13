import ast
import re
from pathlib import Path

from neural_ledger.bootstrap.config import Settings
from neural_ledger.bootstrap.container import build

ROOT = Path(__file__).resolve().parents[3]
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _keys_read_by_config() -> set[str]:
    """Every environment variable Settings.from_env reads: the name in get(NAME, ...), e.get(NAME) or e[NAME]."""
    tree = ast.parse((ROOT / "backend/src/neural_ledger/bootstrap/config.py").read_text(encoding="utf-8"))
    settings_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Settings")
    from_env = next(node for node in settings_class.body if isinstance(node, ast.FunctionDef) and node.name == "from_env")
    names = [call.args[0] for call in ast.walk(from_env) if isinstance(call, ast.Call) and call.args]
    names += [sub.slice for sub in ast.walk(from_env) if isinstance(sub, ast.Subscript)]
    return {n.value for n in names if isinstance(n, ast.Constant) and isinstance(n.value, str) and ENV_NAME.match(n.value)}


def test_env_example_covers_every_config_read_and_boots_offline():
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    env = dict(line.split("=", 1) for line in template.splitlines() if line and not line.startswith("#"))
    assert set(env) == _keys_read_by_config()
    secrets = [key for key in env if key.endswith(("_API_KEY", "_SECRET"))]
    assert secrets and all(not env[key] for key in secrets), "keys and secrets stay empty in the public template"
    settings = Settings.from_env(env)
    assert settings.mode == "offline" and settings.model_source == "fixture"
    services, _ = build(settings)
    assert services.mode == "offline"
