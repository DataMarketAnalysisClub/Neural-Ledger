"""The architecture is enforced, not just documented.

domain       -> standard library only, nothing else from the project except domain
application  -> standard library + domain + application
adapters     -> anything but bootstrap; inbound and outbound do not import each other
bootstrap    -> anything (it is the composition root)
FastAPI may appear only in adapters/inbound/http.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "neural_ledger"
PROJECT = "neural_ledger"
STDLIB = set(sys.stdlib_module_names) | {"__future__"}


def _module_name(path: Path) -> str:
    rel = path.relative_to(SRC.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            found.append(target)
    return found


def _files(layer: str) -> list[Path]:
    return sorted((SRC / layer).rglob("*.py"))


def _violations(layer: str, allowed_project: tuple[str, ...], allow_third_party: bool) -> list[str]:
    problems = []
    for path in _files(layer):
        for target in _imports(path):
            top = target.split(".")[0]
            if top == PROJECT:
                if not any(target == a or target.startswith(a + ".") for a in allowed_project):
                    problems.append(f"{_module_name(path)} imports {target}")
            elif top not in STDLIB and not allow_third_party:
                problems.append(f"{_module_name(path)} imports third-party {target}")
    return problems


def test_domain_is_pure():
    assert _violations("domain", ("neural_ledger.domain",), allow_third_party=False) == []


def test_application_depends_only_on_domain():
    assert _violations("application", ("neural_ledger.domain", "neural_ledger.application"), allow_third_party=False) == []


@pytest.mark.parametrize(
    "layer, forbidden",
    [
        ("adapters/inbound", ("neural_ledger.adapters.outbound", "neural_ledger.bootstrap")),
        ("adapters/outbound", ("neural_ledger.adapters.inbound", "neural_ledger.bootstrap")),
    ],
)
def test_adapters_do_not_cross(layer, forbidden):
    problems = []
    for path in _files(layer):
        for target in _imports(path):
            if any(target == f or target.startswith(f + ".") for f in forbidden):
                problems.append(f"{_module_name(path)} imports {target}")
    assert problems == []


def test_fastapi_only_in_http_adapter():
    offenders = [
        _module_name(p)
        for p in SRC.rglob("*.py")
        if any(t.split(".")[0] in ("fastapi", "starlette", "pydantic") for t in _imports(p))
        and "adapters/inbound/http" not in p.as_posix()
    ]
    assert offenders == []


def test_core_declares_zero_runtime_dependencies():
    pyproject = (SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in pyproject
