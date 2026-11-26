import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit
import time
import uuid

from .config import ROOT, run_id
from .history import history, read
from .records import run_record, artifacts


def server(store, token, host="127.0.0.1", port=8765, profiles=None):
    if not isinstance(token, str) or len(token) < 24:
        raise ValueError("HAI_SERVICE_TOKEN must contain at least 24 characters")
    profiles = Path(profiles or ROOT / "configs/experiments").resolve()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def json(self, value, status=200):
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def authorized(self):
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self):
            try:
                url = urlsplit(self.path)
                if url.path == "/health":
                    self.json({"status": "ok", "schema": "harnesslens.service.v1"})
                    return
                if not self.authorized():
                    self.json({"error": "Unauthorized"}, 401)
                    return
                parts = url.path.strip("/").split("/")
                if parts == ["v1", "profiles"]:
                    name = parse_qs(url.query).get("name", [""])[0]
                    if name:
                        path = (profiles / name).resolve()
                        if not path.is_relative_to(profiles) or path.suffix != ".toml" or not path.is_file():
                            raise ValueError("Unknown profile")
                        from .settings import profile_preview
                        self.json(profile_preview(path, profiles))
                    else:
                        self.json([str(p.relative_to(profiles)) for p in sorted(profiles.glob("*.toml"))])
                elif parts == ["v1", "dataset"]:
                    from .settings import selected_benchmark
                    from harnesslens.benchmarks.selection import dataset_options
                    benchmark=selected_benchmark(parse_qs(url.query).get('benchmark',[''])[0])
                    self.json(dataset_options(benchmark))
                elif parts == ["v1", "options"]:
                    from .settings import catalog
                    self.json(catalog(profiles))
                elif parts == ["v1", "runs"]:
                    store.sync_local_runs()
                    self.json([run_record(job) for job in store.list()])
                elif len(parts) in {3, 4} and parts[:2] == ["v1", "runs"]:
                    store.sync_local_runs()
                    identity = run_id(parts[2]); job = store.get(identity)
                    if len(parts) == 3:
                        self.json(run_record(job))
                    elif parts[3] == "history":
                        self.json(history(identity))
                    elif parts[3] == "events":
                        after = int(parse_qs(url.query).get("after", ["0"])[0])
                        events = store.events(identity, after)
                        if "text/event-stream" in self.headers.get("Accept", ""):
                            self.send_response(200)
                            self.send_header("Content-Type", "text/event-stream")
                            self.send_header("Cache-Control", "no-store")
                            self.send_header("Connection", "close")
                            self.end_headers()
                            for event in events:
                                self.wfile.write(f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n".encode())
                            if not events:
                                self.wfile.write(b": heartbeat\n\n")
                            self.close_connection = True
                        else:
                            self.json(events)
                    elif parts[3] == "artifacts":
                        import os
                        roots = artifacts(identity, store.directory)
                        files = []
                        for index, root in enumerate(roots):
                            if not root.is_dir(): continue
                            for directory, folders, names in os.walk(root):
                                folders[:] = [f for f in folders if f not in {'node_modules', '.git', '.oc_data', '.oc_cache', '.oc_config', '.cache', '.home', '.tmp', '.venv', '.pytest_cache', '__pycache__', '.npm'}]
                                for name in names:
                                    p = Path(directory) / name
                                    if p.is_symlink() or not p.is_file(): continue
                                    files.append({'root': index, 'path': str(p.relative_to(root)), 'bytes': p.stat().st_size})
                        files.sort(key=lambda x: (Path(x['path']).name not in {'final.json','result.json','background.log','api_calls.jsonl','trial.jsonl','answer.txt','baseline_result.json'}, x['root'], x['path']))
                        self.json(files[:2500])
                    elif parts[3] == "artifact":
                        query = parse_qs(url.query)
                        roots = artifacts(identity, store.directory)
                        index = int(query.get("root", ["0"])[0])
                        if index not in range(len(roots)):
                            raise ValueError("Unknown artifact root")
                        root = roots[index].resolve()
                        path = (root / query.get("path", [""])[0]).resolve()
                        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
                            raise ValueError("Artifact unavailable or too large")
                        self.json({"path": str(path.relative_to(root)), "content": path.read_text(errors="replace")})
                    else:
                        self.json({"error": "Not found"}, 404)
                else:
                    self.json({"error": "Not found"}, 404)
            except KeyError:
                self.json({"error": "Not found"}, 404)
            except (ValueError, OSError) as exc:
                self.json({"error": str(exc)}, 400)

        def do_POST(self):
            if not self.authorized():
                self.json({"error": "Unauthorized"}, 401); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("Invalid request size")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Request must be a JSON object")
                parts = urlsplit(self.path).path.strip("/").split("/")
                if parts == ["v1", "runs"]:
                    profile = (profiles / str(body["profile"])).resolve()
                    if not profile.is_relative_to(profiles) or profile.suffix != ".toml" or not profile.is_file():
                        raise ValueError("Profile must belong to the configured profile directory")
                    identity = body.get("run_id") or "run_" + time.strftime("%Y%m%d_%H%M%S", time.gmtime()) + "_" + uuid.uuid4().hex[:8]
                    self.json(store.create(identity, profile, settings=body.get("settings"), profiles=profiles), 201)
                elif len(parts) == 4 and parts[:2] == ["v1", "runs"]:
                    self.json(store.transition(run_id(parts[2]), parts[3]))
                else:
                    self.json({"error": "Not found"}, 404)
            except KeyError:
                self.json({"error": "Missing field or run"}, 400)
            except sqlite3.IntegrityError:
                self.json({"error": "Run ID already exists"}, 409)
            except (ValueError, OSError) as exc:
                self.json({"error": str(exc)}, 400)
    return ThreadingHTTPServer((host, port), Handler)
