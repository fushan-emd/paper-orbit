from __future__ import annotations

from pathlib import Path
from typing import Any

import json
import tomllib


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    if config_path.suffix.lower() == ".toml":
        with config_path.open("rb") as handle:
            config = tomllib.load(handle)
    elif config_path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ModuleNotFoundError as exc:
            raise RuntimeError("YAML config requires PyYAML. Use config.toml or install PyYAML.") from exc
        with config_path.open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
    else:
        raise ValueError("Config must be .toml, .yaml, or .yml")

    required = ["project", "run", "profile", "sources", "weights"]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing config sections: {', '.join(missing)}")

    return config


def write_config(config: dict[str, Any], path: str | Path) -> None:
    config_path = Path(path)
    tmp_path = config_path.with_suffix(config_path.suffix + ".tmp.toml")
    backup_path = config_path.with_suffix(config_path.suffix + ".bak")
    tmp_path.write_text(_dump_toml(config), encoding="utf-8")
    load_config(tmp_path)
    if config_path.exists():
        backup_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    tmp_path.replace(config_path)


def _dump_toml(config: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in config.items():
        if isinstance(value, dict):
            _dump_table(lines, key, value)
        else:
            lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines).rstrip() + "\n"


def _dump_table(lines: list[str], name: str, table: dict[str, Any]) -> None:
    simple_items = {key: value for key, value in table.items() if not isinstance(value, dict)}
    nested_items = {key: value for key, value in table.items() if isinstance(value, dict)}

    lines.append("")
    lines.append(f"[{name}]")
    for key, value in simple_items.items():
        lines.append(f"{_toml_key(key)} = {_toml_value(value)}")

    for key, value in nested_items.items():
        _dump_table(lines, f"{name}.{key}", value)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(isinstance(item, str) for item in value):
            joined = ", ".join(_toml_string(item) for item in value)
            return f"[{joined}]"
        joined = ", ".join(_toml_value(item) for item in value)
        return f"[{joined}]"
    return _toml_string(str(value))


def _toml_key(value: str) -> str:
    cleaned = value.strip().replace("\r", "").replace("\n", "")
    if cleaned.replace("_", "").replace("-", "").isalnum():
        return cleaned
    return _toml_string(cleaned)


def _toml_string(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return json.dumps(normalized, ensure_ascii=False)
