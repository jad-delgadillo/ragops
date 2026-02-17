#!/usr/bin/env python3
"""Initialize the Neon (or any Postgres+pgvector) database with the RAG Ops schema."""

from __future__ import annotations

import sys

import psycopg
from pgvector.psycopg import register_vector


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/init_neon.py <connection_string>")
        print("  e.g. python scripts/init_neon.py 'postgresql://user:pass@host/db?sslmode=require'")
        sys.exit(1)

    conninfo = sys.argv[1]
    print(f"🔗 Connecting to database...")

    conn = psycopg.connect(conninfo, autocommit=True)

    # Create pgvector extension first, then register types
    print("📦 Enabling pgvector extension...")
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)

    print("✅ Connected!")

    # Read and execute schema
    from pathlib import Path

    schema_path = Path(__file__).resolve().parent.parent / "services" / "core" / "schema.sql"
    schema_sql = schema_path.read_text()

    print("📦 Applying schema (pgvector + tables)...")
    conn.execute(schema_sql)
    print("✅ Schema applied successfully!")

    # Verify
    row = conn.execute("SELECT COUNT(*) AS cnt FROM documents").fetchone()
    print(f"📊 Documents table has {row[0]} rows")

    row = conn.execute("SELECT COUNT(*) AS cnt FROM chunks").fetchone()
    print(f"📊 Chunks table has {row[0]} rows")

    conn.close()
    print("🎉 Neon database initialized!")


if __name__ == "__main__":
    main()
