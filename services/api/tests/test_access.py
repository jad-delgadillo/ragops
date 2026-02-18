"""Tests for API key authorization policy."""

from __future__ import annotations

import pytest

from services.api.app.access import authorize, load_api_key_policy
from services.core.config import Settings


def test_authorize_allows_when_auth_disabled() -> None:
    settings = Settings(_env_file=None, API_AUTH_ENABLED="false", OPENAI_API_KEY="test")
    decision = authorize(
        settings=settings,
        headers={},
        action="query",
        collection="default",
    )
    assert decision.allowed


def test_authorize_denies_missing_key_when_enabled() -> None:
    settings = Settings(
        _env_file=None,
        API_AUTH_ENABLED="true",
        API_KEYS_JSON="{}",
        OPENAI_API_KEY="test",
    )
    decision = authorize(
        settings=settings,
        headers={},
        action="query",
        collection="default",
    )
    assert not decision.allowed
    assert "Missing X-API-Key" in decision.reason


def test_authorize_allows_action_and_collection() -> None:
    policy = (
        '{"k1":{"name":"bot","permissions":["query","chat"],'
        '"collections":["default","ragops"]}}'
    )
    settings = Settings(
        _env_file=None,
        API_AUTH_ENABLED="true",
        API_KEYS_JSON=policy,
        OPENAI_API_KEY="test",
    )
    decision = authorize(
        settings=settings,
        headers={"X-API-Key": "k1"},
        action="chat",
        collection="ragops",
    )
    assert decision.allowed
    assert decision.principal == "bot"


def test_load_policy_rejects_non_object() -> None:
    settings = Settings(
        _env_file=None,
        API_AUTH_ENABLED="true",
        API_KEYS_JSON='["bad"]',
        OPENAI_API_KEY="test",
    )
    with pytest.raises(ValueError):
        load_api_key_policy(settings)


def test_authorize_denies_repo_manage_when_permission_missing() -> None:
    policy = '{"k1":{"name":"bot","permissions":["query","chat"],"collections":["*"]}}'
    settings = Settings(
        _env_file=None,
        API_AUTH_ENABLED="true",
        API_KEYS_JSON=policy,
        OPENAI_API_KEY="test",
    )
    decision = authorize(
        settings=settings,
        headers={"X-API-Key": "k1"},
        action="repo_manage",
        collection="default",
    )
    assert not decision.allowed
    assert "repo_manage" in decision.reason
