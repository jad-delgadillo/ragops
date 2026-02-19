"""User-level ragops config helpers (~/.ragops/config.yaml)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

USER_CONFIG_DIR = ".ragops"
USER_CONFIG_FILE = "config.yaml"


def user_config_path(home: Path | None = None) -> Path:
    """Return absolute path to user-level config file."""
    base = home.expanduser().resolve() if home else Path.home().resolve()
    return base / USER_CONFIG_DIR / USER_CONFIG_FILE


def load_user_config(home: Path | None = None) -> dict[str, Any]:
    """Load user config, returning empty dict when absent/invalid."""
    path = user_config_path(home)
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def save_user_config(values: dict[str, Any], home: Path | None = None) -> Path:
    """Merge and persist user-level config."""
    path = user_config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = load_user_config(home)
    payload.update(values)
    payload["updated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    try:
        path.chmod(0o600)
    except Exception:
        # Ignore platforms/filesystems that do not support chmod semantics.
        pass
    return path

