"""Collection-scoped API key authorization helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from services.core.config import Settings


@dataclass
class AccessDecision:
    """Authorization decision for a request."""

    allowed: bool
    reason: str = ""
    principal: str = "anonymous"
    key_id: str = ""
    permissions: set[str] = field(default_factory=set)
    collections: set[str] = field(default_factory=set)


def normalize_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    """Normalize header map to lowercase keys + string values."""
    if not headers:
        return {}
    normalized: dict[str, str] = {}
    for key, value in headers.items():
        normalized[str(key).lower()] = str(value)
    return normalized


def load_api_key_policy(settings: Settings) -> dict[str, dict[str, Any]]:
    """Parse API key policy JSON from settings."""
    raw = (settings.api_keys_json or "{}").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("API_KEYS_JSON must be a JSON object keyed by API key")
    out: dict[str, dict[str, Any]] = {}
    for key, value in parsed.items():
        if not isinstance(value, dict):
            raise ValueError(f"API key policy entry for '{key}' must be an object")
        out[str(key)] = value
    return out


def _normalize_scope_list(raw_value: Any) -> set[str]:
    """Normalize policy list value to a set of lowercase strings."""
    if raw_value is None:
        return set()
    if isinstance(raw_value, str):
        return {raw_value.strip().lower()} if raw_value.strip() else set()
    if isinstance(raw_value, list):
        return {str(v).strip().lower() for v in raw_value if str(v).strip()}
    raise ValueError("Policy fields 'permissions' and 'collections' must be string or list")


def authorize(
    *,
    settings: Settings,
    headers: dict[str, Any] | None,
    action: str,
    collection: str,
) -> AccessDecision:
    """Authorize request by API key policy, optionally bypassed when disabled."""
    if not settings.api_auth_enabled:
        return AccessDecision(
            allowed=True,
            principal="auth_disabled",
            permissions={"*"},
            collections={"*"},
        )

    normalized_headers = normalize_headers(headers)
    api_key = normalized_headers.get("x-api-key", "").strip()
    if not api_key:
        return AccessDecision(allowed=False, reason="Missing X-API-Key header")

    policy = load_api_key_policy(settings)
    entry = policy.get(api_key)
    if not entry:
        return AccessDecision(allowed=False, reason="Invalid API key")

    permissions = _normalize_scope_list(entry.get("permissions", ["query", "chat", "feedback"]))
    collections = _normalize_scope_list(entry.get("collections", ["default"]))
    if "*" not in permissions and action.lower() not in permissions:
        return AccessDecision(
            allowed=False,
            reason=f"API key does not allow action '{action}'",
        )
    if "*" not in collections and collection.lower() not in collections:
        return AccessDecision(
            allowed=False,
            reason=f"API key does not allow collection '{collection}'",
        )

    principal = str(entry.get("name", "api_client")).strip() or "api_client"
    key_id = str(entry.get("key_id", "")) or api_key[:6]
    return AccessDecision(
        allowed=True,
        principal=principal,
        key_id=key_id,
        permissions=permissions,
        collections=collections,
    )
