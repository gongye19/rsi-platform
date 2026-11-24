#!/usr/bin/env python3
"""Initialize a NEW isolated benchmark DB; never overwrites an existing DB/role."""
import argparse
import hashlib
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create-isolated-benchmark-db", action="store_true", required=True)
    args = parser.parse_args()
    from harnesslens.core.config import load_repo_env
    from harnesslens.benchmarks.crm import PG_DATABASE, PG_READER, dataset_root, data_fingerprint
    load_repo_env(ROOT)
    import psycopg2
    from psycopg2 import sql
    dsn = os.environ.get("CRM_BENCHMARK_ADMIN_DSN")
    if not dsn:
        parser.error("Set CRM_BENCHMARK_ADMIN_DSN for a dedicated test PostgreSQL instance (not production)")
    data_fingerprint(ROOT)
    dump = dataset_root(ROOT) / "query_dataset/support.sql"
    marker = "harness2-crm:" + hashlib.sha256(dump.read_bytes()).hexdigest()
    admin = psycopg2.connect(dsn)
    try:
        admin.autocommit = True
        with admin.cursor() as cursor:
            cursor.execute("SELECT datname FROM pg_database WHERE datname=%s", (PG_DATABASE,))
            exists = cursor.fetchone()
            cursor.execute("SELECT rolname FROM pg_roles WHERE rolname=%s", (PG_READER,))
            if exists or cursor.fetchone():
                raise RuntimeError("Benchmark DB or reader already exists; refusing modification. Use check_intranet.py --crm to verify.")
            cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION").format(sql.Identifier(PG_READER)))
            cursor.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(sql.Identifier(PG_READER)))
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(PG_DATABASE)))
    finally:
        admin.close()
    params = psycopg2.extensions.parse_dsn(dsn)
    params["dbname"] = PG_DATABASE
    with psycopg2.connect(**params) as connection:
        with connection.cursor() as cursor:
            cursor.execute(dump.read_text())
            cursor.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(PG_READER)))
            cursor.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(PG_READER)))
            cursor.execute(sql.SQL("REVOKE CREATE,TEMP ON DATABASE {} FROM PUBLIC").format(sql.Identifier(PG_DATABASE)))
            cursor.execute(sql.SQL("COMMENT ON DATABASE {} IS %s").format(sql.Identifier(PG_DATABASE)), (marker,))
    print("Isolated benchmark imported. Configure loopback read-only role access, then verify the canonical fingerprint.")


if __name__ == "__main__":
    main()
