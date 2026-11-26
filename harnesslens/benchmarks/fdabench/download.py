"""Pinned, resumable server downloads. No model calls and no credential persistence."""

from __future__ import annotations
import concurrent.futures
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from harnesslens.core.artifacts import write_json
from .data import sha, tasks, rows
from .adapter import asset_manifest


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ValueError("Refusing non-HTTPS redirect")
        result = super().redirect_request(
            request, response, code, message, headers, url
        )
        if (
            result
            and urllib.parse.urlsplit(request.full_url).netloc
            != urllib.parse.urlsplit(url).netloc
        ):
            result.remove_header("Authorization")
        return result


HTTP = urllib.request.build_opener(SafeRedirect())


def open_url(url, *, headers=None, timeout=90):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError("HTTPS sources required")
    auth = {}
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if token and parsed.hostname == "huggingface.co":
        auth["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers={**auth, **(headers or {})})
    for attempt in range(3):
        try:
            return HTTP.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError(
                    "HF source access denied: obtain dataset access and set HF_TOKEN on the server"
                ) from None
            if exc.code != 429 and exc.code < 500 or attempt == 2:
                raise RuntimeError("Download HTTP " + str(exc.code)) from None
        except (TimeoutError, urllib.error.URLError):
            if attempt == 2:
                raise RuntimeError(
                    "Download transport failed after 3 attempts"
                ) from None
        time.sleep(attempt + 1)


def safe_target(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe asset path")
    target = Path(root) / relative
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError("Symlink asset paths are unsupported")
    return target


def valid(path, item):
    if not path.is_file() or path.stat().st_size != item.get("bytes", item.get("size")):
        return False
    if item.get("sha256"):
        return sha(path) == item["sha256"]
    if item.get("git_blob"):
        h = hashlib.sha1(("blob " + str(path.stat().st_size) + "\0").encode())
        with path.open("rb") as f:
            while block := f.read(1024**2):
                h.update(block)
        return h.hexdigest() == item["git_blob"]
    raise ValueError("Asset manifest needs a content digest")


def save_stream(stream, target, item):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    try:
        expected = item.get("bytes", item.get("size"))
        size = 0
        with temporary.open("wb") as out:
            while block := stream.read(1024**2):
                size += len(block)
                if size > expected:
                    raise ValueError("Asset exceeds pinned size")
                out.write(block)
        if not valid(temporary, item):
            raise ValueError("Pinned content digest/size mismatch: " + target.name)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


class Remote(io.RawIOBase):
    """Bounded seekable ZIP reader; range responses are checked before use."""

    def __init__(self, url, start=0, length=None):
        self.url, self.start, self.pos = url, start, 0
        if length is None:
            with open_url(url, headers={"Range": "bytes=0-0"}) as response:
                if response.status != 206:
                    raise ValueError("Source must support byte ranges")
                length = int(response.headers["Content-Range"].split("/")[-1])
        self.size = length

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        position = (
            offset
            if whence == 0
            else self.pos + offset
            if whence == 1
            else self.size + offset
        )
        if position < 0:
            raise ValueError("Negative range seek")
        self.pos = position
        return self.pos

    def read(self, size=-1):
        size = self.size - self.pos if size < 0 else min(size, self.size - self.pos)
        chunks = []
        while size > 0:
            count = min(size, 4 * 1024**2)
            begin = self.start + self.pos
            with open_url(
                self.url, headers={"Range": f"bytes={begin}-{begin + count - 1}"}
            ) as response:
                if response.status != 206 or not response.headers.get(
                    "Content-Range", ""
                ).startswith(f"bytes {begin}-{begin + count - 1}/"):
                    raise ValueError("Incorrect HTTP byte range")
                data = response.read(count + 1)
            if len(data) != count:
                raise ValueError("Truncated byte range")
            chunks.append(data)
            self.pos += count
            size -= count
        return b"".join(chunks)


@contextmanager
def archives(url):
    remote = Remote(url)
    opened = []
    try:
        outer = zipfile.ZipFile(remote)
        opened.append(outer)
        for member in outer.infolist():
            if (
                member.filename.endswith(".zip")
                and member.compress_type == zipfile.ZIP_STORED
            ):
                remote.seek(member.header_offset)
                header = struct.unpack("<4s5H3I2H", remote.read(30))
                if header[0] != b"PK\x03\x04":
                    raise ValueError("Invalid nested ZIP header")
                offset = member.header_offset + 30 + header[-2] + header[-1]
                opened.append(
                    zipfile.ZipFile(Remote(url, start=offset, length=member.file_size))
                )
        yield opened
    finally:
        for archive in opened:
            archive.close()


def download_databases(root, manifest):
    groups = {}
    for item in manifest["databases"]:
        target = safe_target(root, item["local_path"])
        if not valid(target, item):
            groups.setdefault(item["url"], []).append(item)
    for url, wanted in groups.items():
        if any("archive_member" in item for item in wanted):
            with archives(url) as sources:
                for item in wanted:
                    found = [
                        (a, m)
                        for a in sources
                        for m in a.infolist()
                        if m.filename == item["archive_member"]
                        or (
                            "/" not in item["archive_member"]
                            and Path(m.filename).name == item["archive_member"]
                        )
                    ]
                    if len(found) != 1:
                        raise ValueError(
                            "Expected one pinned database archive member: " + item["db"]
                        )
                    archive, member = found[0]
                    with archive.open(member) as stream:
                        save_stream(stream, safe_target(root, item["local_path"]), item)
        elif any("tar_member" in item for item in wanted):
            # Streaming tar avoids retaining the complete code archive in memory.
            pending = {i["tar_member"]: i for i in wanted}
            with (
                open_url(url) as response,
                tarfile.open(fileobj=response, mode="r|gz") as archive,
            ):
                for member in archive:
                    if member.name in pending:
                        if not member.isfile():
                            raise ValueError("Pinned tar member is not a regular file")
                        item = pending.pop(member.name)
                        with archive.extractfile(member) as stream:
                            save_stream(
                                stream, safe_target(root, item["local_path"]), item
                            )
                        if not pending:
                            break
            if pending:
                raise ValueError("Pinned database missing from code archive")
        else:
            for item in wanted:
                with open_url(url) as response:
                    save_stream(response, safe_target(root, item["local_path"]), item)
        print(
            json.dumps({"databases_downloaded": [i["db"] for i in wanted]}), flush=True
        )


def download_tasks(root, manifest):
    url = f"https://huggingface.co/datasets/FDAbench2026/Fdabench-Lite/resolve/{manifest['lite_revision']}/report/data.jsonl"
    with open_url(url) as response:
        raw = response.read(20 * 1024**2 + 1)
    if hashlib.sha256(raw).hexdigest() != manifest["tasks_sha256"]:
        raise ValueError("Pinned task source changed")
    raw_rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    fields = (
        "task_id",
        "instance_id",
        "db",
        "database_type",
        "db_type",
        "level",
        "question_type",
        "query",
        "tools_available",
    )
    for name, values in [
        ("tasks/tasks.jsonl", [{k: r[k] for k in fields if k in r} for r in raw_rows]),
        (
            "evaluation/references.jsonl",
            [
                {k: v for k, v in r.items() if k not in fields or k == "task_id"}
                for r in raw_rows
            ],
        ),
    ]:
        path = safe_target(root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".part")
        temp.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in values)
        )
        temp.replace(path)
    tasks(root)
    from harnesslens.benchmarks.benchmark_splits import load_benchmark_split

    split = load_benchmark_split("fdabench")
    eligible = {
        r["task_id"]
        for r in raw_rows
        if r.get("ground_truth_report") and r.get("rubric")
    }
    if eligible != set(split.train + split.test):
        raise ValueError("Released reference eligibility differs from frozen split")
    listing = [
        {
            "path": d["path"],
            "size": d["size"],
            **(
                {"lfs": {"oid": d["sha256"]}}
                if d.get("sha256")
                else {"oid": d["git_blob"]}
            ),
        }
        for d in manifest["documents"]
    ]
    write_json(Path(root) / "metadata/corpus_file_listing.json", listing)
    write_json(Path(root) / "metadata/databases.json", manifest["databases"])


def download(root, *, workers=6, section="all"):
    if not 1 <= workers <= 16:
        raise ValueError("workers must be 1..16")
    manifest = asset_manifest()
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    import fcntl

    with (root / ".download.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        download_tasks(root, manifest)
        if section in ("all", "databases"):
            download_databases(root, manifest)
        if section in ("all", "documents"):

            def fetch(item):
                target = safe_target(root / "documents", item["path"])
                if not valid(target, item):
                    url = (
                        f"https://huggingface.co/datasets/FDAbench2026/FDABench-File/resolve/{manifest['corpus_revision']}/"
                        + urllib.parse.quote(item["path"], safe="/")
                    )
                    with open_url(url) as response:
                        save_stream(response, target, item)

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                for n, _ in enumerate(pool.map(fetch, manifest["documents"]), 1):
                    if n % 25 == 0:
                        print(
                            json.dumps(
                                {
                                    "verified_files": n,
                                    "total": len(manifest["documents"]),
                                }
                            ),
                            flush=True,
                        )
    print("Download section complete. Run prepare next.", flush=True)


def verify(root):
    manifest = asset_manifest()
    root = Path(root)
    tasks(root)
    for item in manifest["databases"]:
        if not valid(safe_target(root, item["local_path"]), item):
            raise ValueError("Database missing/changed: " + item["db"])
    for item in manifest["documents"]:
        if not valid(safe_target(root / "documents", item["path"]), item):
            raise ValueError("PDF missing/changed: " + item["path"])
    # Validate semantic projections against pins, including host-only gold records.
    for key, path in [
        ("public_tasks", "tasks/tasks.jsonl"),
        ("references", "evaluation/references.jsonl"),
    ]:
        digest = hashlib.sha256(
            json.dumps(
                rows(root / path),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if digest != manifest[key + "_canonical_sha256"]:
            raise ValueError("Pinned task/reference projection changed")
    receipt = {
        "assets_sha256": sha(
            Path(__file__).resolve().parents[3] / "configs/fdabench-assets.json"
        ),
        "tasks_sha256": sha(root / "tasks/tasks.jsonl"),
        "references_sha256": sha(root / "evaluation/references.jsonl"),
        "pdf_count": sum(
            d["path"].lower().endswith(".pdf") for d in manifest["documents"]
        ),
        "database_count": len(manifest["databases"]),
    }
    write_json(root / "metadata/verified-assets.json", receipt)
    return receipt
