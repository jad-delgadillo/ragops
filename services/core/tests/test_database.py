"""Unit tests for DB helper utilities."""

import pytest

from services.core.database import normalize_db_url, parse_vector_dimension


def test_parse_vector_dimension_fixed() -> None:
    assert parse_vector_dimension("vector(1536)") == 1536


def test_parse_vector_dimension_unbounded() -> None:
    assert parse_vector_dimension("vector") is None


def test_parse_vector_dimension_invalid() -> None:
    assert parse_vector_dimension("text") is None


def test_normalize_db_url_rejects_boolean_literal() -> None:
    with pytest.raises(ValueError, match="boolean-like value"):
        normalize_db_url("yes")


def test_normalize_db_url_accepts_postgres_dsn() -> None:
    dsn = "postgresql://user:pass@host/db?sslmode=require"
    assert normalize_db_url(dsn) == dsn
