# Adapted from the earlier RSI Platform FDABench integration; standalone implementation.
"""Public-only FDABench inputs and a reproducible full-corpus lexical index."""

from __future__ import annotations
import concurrent.futures
from contextlib import closing
import hashlib
import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rows(path):
    return [
        json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()
    ]


def tasks(root):
    result = rows(Path(root) / "tasks/tasks.jsonl")
    allowed = {
        "task_id",
        "instance_id",
        "db",
        "database_type",
        "db_type",
        "level",
        "question_type",
        "query",
        "tools_available",
    }
    if len(result) != 117 or len({x["task_id"] for x in result}) != 117:
        raise ValueError("Expected exactly 117 unique report tasks")
    for row in result:
        if (
            set(row) - allowed
            or row["question_type"] != "report"
            or row["db_type"] != "sqlite"
        ):
            raise ValueError("Unexpected task input fields or type")
        if not re.fullmatch(r"[A-Za-z0-9_]+", row["db"]):
            raise ValueError("Invalid database name")
    return {x["task_id"]: x for x in result}


def corpus_files(root):
    """Use only public PDF paths; never use reference-hit lists to build the index."""
    root = Path(root)
    entries = json.loads((root / "metadata/corpus_file_listing.json").read_text())
    files = [e for e in entries if e["path"].lower().endswith(".pdf")]
    if len(files) != 1418:
        raise ValueError("Expected complete 1418-PDF corpus")
    for e in files:
        relative = Path(e["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe PDF path")
        p = root / "documents" / relative
        if p.is_symlink() or not p.resolve().is_relative_to(
            (root / "documents").resolve()
        ):
            raise ValueError("PDF path leaves document corpus")
        if not p.is_file() or p.stat().st_size != e["size"]:
            raise ValueError("Missing or incomplete PDF: " + e["path"])
    return files


def extract(item):
    root, entry = item
    data = subprocess.run(
        [
            "pdftotext",
            "-layout",
            "-enc",
            "UTF-8",
            str(root / "documents" / entry["path"]),
            "-",
        ],
        capture_output=True,
        timeout=120,
        check=True,
    ).stdout.decode("utf-8", errors="replace")
    chunks = []
    for page, text in enumerate(data.split("\f"), 1):
        text = re.sub(r"\s+", " ", text).strip()
        for offset in range(0, len(text), 1600):
            chunk = text[offset : offset + 1800]
            if chunk.strip():
                chunks.append((entry["path"], page, chunk))
    return entry["path"], chunks


def _build_index(root, cache, workers):
    root, cache = Path(root), Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    entries = corpus_files(root)
    version = (
        subprocess.run(["pdftotext", "-v"], capture_output=True, check=True)
        .stderr.decode()
        .splitlines()[0]
    )
    identity = hashlib.sha256(
        json.dumps(
            {
                "pdfs": entries,
                "extractor": version,
                "chunk": [1800, 1600],
                "index": "sqlite-fts5-porter-unicode61-v1",
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    path, receipt = cache / "documents.sqlite", cache / "index.json"
    if path.exists() and receipt.exists():
        saved = json.loads(receipt.read_text())
        if saved["input_identity"] == identity and saved["index_sha256"] == sha(path):
            return path, saved
        raise ValueError("Index identity changed; use a new cache directory")
    temporary = cache / "documents.partial.sqlite"
    temporary.unlink(missing_ok=True)
    count = 0
    with closing(sqlite3.connect(temporary)) as connection, connection:
        connection.execute(
            "CREATE VIRTUAL TABLE chunks USING fts5(path UNINDEXED, page UNINDEXED, text, tokenize='porter unicode61')"
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for i, (name, chunks) in enumerate(
                pool.map(extract, ((root, e) for e in entries)), 1
            ):
                connection.executemany(
                    "INSERT INTO chunks(path,page,text) VALUES (?,?,?)", chunks
                )
                count += len(chunks)
                if i % 100 == 0:
                    connection.commit()
                    print(
                        json.dumps(
                            {"indexing_pdfs": i, "total": len(entries), "chunks": count}
                        ),
                        flush=True,
                    )
        connection.execute("INSERT INTO chunks(chunks) VALUES ('optimize')")
    temporary.replace(path)
    result = {
        "input_identity": identity,
        "index_sha256": sha(path),
        "pdf_count": len(entries),
        "chunks": count,
        "retriever": "SQLite FTS5 BM25; lexical, not official OpenAI embedding/FAISS retrieval",
        "pdftotext_version": version,
        "empty_pdf_count": 0,
    }
    with closing(sqlite3.connect(path)) as c:
        result["indexed_pdf_count"] = c.execute(
            "SELECT count(distinct path) FROM chunks"
        ).fetchone()[0]
    result["empty_pdf_count"] = len(entries) - result["indexed_pdf_count"]
    from harnesslens.core.artifacts import write_json

    result["corpus_listing_sha256"] = sha(root / "metadata/corpus_file_listing.json")
    result["verified_assets_sha256"] = sha(root / "metadata/verified-assets.json")
    write_json(receipt, result)
    return path, result


def sql_query(path, sql, limit=200):
    limit = min(max(int(limit), 1), 1000)
    deadline = time.monotonic() + 20
    with closing(
        sqlite3.connect(f"file:{Path(path)}?mode=ro&immutable=1", uri=True)
    ) as connection:
        connection.execute("PRAGMA query_only=ON")
        allowed = {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
            sqlite3.SQLITE_RECURSIVE,
        }

        def authorize(action, arg1, arg2, *_):
            if action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() in (
                "load_extension",
                "writefile",
                "readfile",
            ):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

        connection.set_authorizer(authorize)
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        cursor = connection.execute(sql)
        names = [d[0] for d in cursor.description or []]
        data = cursor.fetchmany(limit + 1)
    return {
        "columns": names,
        "rows": data[:limit],
        "truncated": len(data) > limit,
        "limit": limit,
    }


def schema(path):
    result = sql_query(
        path,
        "SELECT name, sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'",
        1000,
    )
    return {"tables": [{"name": x[0], "ddl": x[1]} for x in result["rows"]]}


def search(index, query, limit=5):
    terms = re.findall(r"\w+", query, flags=re.UNICODE)[:40]
    if not terms:
        raise ValueError("Search requires words")
    # Quote each token: user queries cannot inject FTS expressions.
    expression = " OR ".join('"' + x.replace('"', '""') + '"' for x in terms)
    with closing(sqlite3.connect(f"file:{Path(index)}?mode=ro", uri=True)) as c:
        found = c.execute(
            "SELECT path,page,text,bm25(chunks) FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks),rowid LIMIT ?",
            (expression, min(max(int(limit), 1), 20)),
        ).fetchall()
    return {
        "retriever": "fts5_bm25",
        "query": query,
        "results": [
            {"path": p, "page": page, "text": text, "rank_score": -score}
            for p, page, text, score in found
        ],
    }


def read_document(index, path, page=1):
    with closing(sqlite3.connect(f"file:{Path(index)}?mode=ro", uri=True)) as c:
        found = c.execute(
            "SELECT text FROM chunks WHERE path=? AND page=? ORDER BY rowid LIMIT 15",
            (path, int(page)),
        ).fetchall()
    return {"path": path, "page": int(page), "chunks": [r[0] for r in found]}


def build_index(root, cache, *, workers=4):
    import fcntl

    if not 1 <= workers <= 16:
        raise ValueError("index workers must be 1..16")
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / ".index.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _build_index(root, cache, workers)
