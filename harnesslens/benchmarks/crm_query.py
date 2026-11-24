"""Generic read-only database access copied into each task's source directory."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("schema", "sql"))
    parser.add_argument("database")
    parser.add_argument("statement", nargs="?")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    databases = json.loads((root / "connections.json").read_text())
    settings = databases[args.database]
    kind = settings["type"]
    if kind == "postgres":
        import psycopg2
        connection = psycopg2.connect(settings["dsn"])
        connection.set_session(readonly=True)
        cursor = connection.cursor()
        cursor.execute("SET LOCAL statement_timeout = '90s'")
    elif kind == "duckdb":
        import duckdb
        connection = duckdb.connect(str(root / settings["path"]), read_only=True)
        cursor = connection.cursor()
    else:
        connection = sqlite3.connect((root / settings["path"]).as_uri() + "?mode=ro", uri=True)
        cursor = connection.cursor()
    try:
        if args.command == "schema":
            if kind == "sqlite":
                statement = "SELECT name, sql FROM sqlite_master WHERE type='table'"
            else:
                statement = "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema='public' OR table_schema='main' ORDER BY table_name, ordinal_position"
        else:
            if not args.statement:
                parser.error("sql requires a statement")
            statement = args.statement
        cursor.execute(statement)
        columns = [item[0] for item in cursor.description] if cursor.description else []
        limit = max(1, min(args.limit, 1000))
        values = cursor.fetchmany(limit + 1)
        print(json.dumps({"columns": columns, "rows": values[:limit], "truncated": len(values) > limit}, default=str, ensure_ascii=False))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
