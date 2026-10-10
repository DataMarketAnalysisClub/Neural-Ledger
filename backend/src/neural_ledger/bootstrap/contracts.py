"""Load tool definitions from contracts/tools/*.input.schema.json (the single source of truth)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..application.services.tools import ToolDefinition

_META_KEYS = {"$schema", "$id", "title", "x-tier", "x-owner", "x-stateful"}


def load_tool_definitions(contracts_dir: Path) -> dict[str, ToolDefinition]:
    tools_dir = Path(contracts_dir) / "tools"
    definitions: dict[str, ToolDefinition] = {}
    for path in sorted(tools_dir.glob("*.input.schema.json")):
        schema: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        name = path.name.removesuffix(".input.schema.json")
        description = schema.get("description", "")
        definitions[name] = ToolDefinition(description, {k: v for k, v in schema.items() if k not in _META_KEYS | {"description"}})
    if not definitions:
        raise FileNotFoundError(f"no tool contracts found in {tools_dir}")
    return definitions


def contract_tiers(contracts_dir: Path) -> dict[str, str]:
    tools_dir = Path(contracts_dir) / "tools"
    return {
        p.name.removesuffix(".input.schema.json"): json.loads(p.read_text(encoding="utf-8")).get("x-tier", "")
        for p in sorted(tools_dir.glob("*.input.schema.json"))
    }
