"""Restricted proxy to the existing, pinned CRM support PostgreSQL database.

Reuses the identity restriction from the local Harness2 CRM adapter. This module
does not create databases, alter roles, import data, or change shared sources.
"""
from __future__ import annotations
import hashlib
import json
import os
import select
import socket
import socketserver
import struct
import threading
from pathlib import Path
from .crm import PG_DATABASE, PG_READER, dataset_root


def pg_port() -> int:
    return int(os.environ.get("HAI_CRM_POSTGRES_PORT", "55432"))


def fingerprint(repo_root: str | Path) -> dict:
    import psycopg2
    from psycopg2 import sql
    result = {}
    with psycopg2.connect(host="127.0.0.1", port=pg_port(), user=PG_READER,
                          dbname=PG_DATABASE, connect_timeout=5) as connection:
        connection.set_session(readonly=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=%s", (PG_DATABASE,))
            marker = cursor.fetchone()[0]
            expected = "harness2-crm:" + hashlib.sha256((dataset_root(repo_root) / "query_dataset/support.sql").read_bytes()).hexdigest()
            if marker != expected:
                raise ValueError("CRM PostgreSQL import marker differs from support.sql")
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
            tables = [row[0] for row in cursor.fetchall()]
            for name in tables:
                cursor.execute("SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (name,))
                columns = cursor.fetchall()
                cursor.execute(sql.SQL("SELECT row_to_json(t)::text FROM public.{} t").format(sql.Identifier(name)))
                rows = sorted(row[0] for row in cursor.fetchall())
                result[name] = {"rows": len(rows), "columns": columns, "sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest()}
    if len(result) != 6 or any(not item["rows"] for item in result.values()):
        raise ValueError("CRM requires the existing six populated support tables")
    result = json.loads(json.dumps({"marker": marker, "tables": result}))
    canonical = Path(repo_root) / "configs/crm_postgres_fingerprint.json"
    if result != json.loads(canonical.read_text()):
        raise ValueError("CRM PostgreSQL contents differ from canonical fingerprint")
    return result


def _read(stream, count):
    data = b""
    while len(data) < count:
        block = stream.recv(count - len(data))
        if not block:
            raise ConnectionError("incomplete PostgreSQL startup")
        data += block
    return data


class ReadOnlyPostgresProxy:
    def __enter__(self):
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                client = self.request
                client.settimeout(5)
                try:
                    for _ in range(3):
                        header = _read(client, 8)
                        length, protocol = struct.unpack("!II", header)
                        if length == 8 and protocol in (80877103, 80877104):
                            client.sendall(b"N")
                            continue
                        if protocol != 196608 or not 9 <= length <= 4096:
                            return
                        body = _read(client, length - 8)
                        fields = body.rstrip(b"\0").split(b"\0")
                        if len(fields) % 2 or len(set(fields[::2])) != len(fields[::2]):
                            return
                        params = dict(zip(fields[::2], fields[1::2]))
                        if params.get(b"user") != PG_READER.encode() or params.get(b"database") != PG_DATABASE.encode() or params.get(b"options"):
                            return
                        with socket.create_connection(("127.0.0.1", pg_port()), 5) as upstream:
                            upstream.sendall(header + body)
                            client.settimeout(None)
                            while True:
                                for source in select.select([client, upstream], [], [], 1)[0]:
                                    block = source.recv(65536)
                                    if not block:
                                        return
                                    (upstream if source is client else client).sendall(block)
                except (OSError, ValueError, struct.error):
                    return
        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
