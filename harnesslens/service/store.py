import json
from pathlib import Path
import sqlite3
import time
from contextlib import contextmanager

from .config import run_id, load_profile


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "state.sqlite"
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, profile TEXT NOT NULL, fingerprint TEXT NOT NULL,
                state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                stop INTEGER DEFAULT 0, attempt INTEGER DEFAULT 0, pid INTEGER, identity TEXT, error TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                run TEXT NOT NULL, at REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);''')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def event(self, identity, kind, payload):
        with self.connect() as db:
            db.execute("INSERT INTO events(run,at,kind,payload) VALUES(?,?,?,?)", (identity, time.time(), kind, json.dumps(payload)))

    def create(self, identity, path):
        run_id(identity)
        profile = load_profile(path)
        now = time.time()
        with self.connect() as db:
            db.execute("INSERT INTO jobs(id,profile,fingerprint,state,created,updated) VALUES(?,?,?,?,?,?)",
                       (identity, str(Path(path).resolve()), profile["fingerprint"], "draft", now, now))
        self.event(identity, "created", {"mode": profile["mode"], "benchmark": profile["benchmark"]})
        return self.get(identity)

    def get(self, identity):
        run_id(identity)
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        return dict(row)

    def list(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY created DESC")]

    def transition(self, identity, action):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (identity,)).fetchone()
            if row is None:
                raise KeyError(identity)
            if action in {"start", "resume"}:
                permitted = {"draft"} if action == "start" else {"stopped", "failed", "interrupted"}
                if row["state"] not in permitted:
                    raise ValueError("Run cannot start/resume from its current state")
                profile = load_profile(row["profile"])
                if profile["fingerprint"] != row["fingerprint"]:
                    raise ValueError("Experiment profile changed; create a new run")
                if profile.get("readiness", "ready") != "ready":
                    raise ValueError("Draft profile: business/data/trace integration is not ready")
                from .config import invocation
                invocation(profile, identity)  # Validate both connections before queueing.
                db.execute("UPDATE jobs SET state='queued',stop=0,error='',updated=? WHERE id=?", (time.time(), identity))
            elif action == "stop":
                if row["state"] not in {"queued", "running", "stopping"}:
                    raise ValueError("Run is not active")
                state = "stopped" if row["state"] == "queued" else "stopping"
                db.execute("UPDATE jobs SET state=?,stop=1,updated=? WHERE id=?", (state, time.time(), identity))
            else:
                raise ValueError("Unknown action")
        self.event(identity, action, {})
        return self.get(identity)

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET state='running',attempt=attempt+1,updated=? WHERE id=?", (time.time(), row["id"]))
        return self.get(row["id"])

    def update(self, job_id, **fields):
        if set(fields) - {"state", "pid", "identity", "error"}:
            raise ValueError("Invalid job field")
        fields["updated"] = time.time()
        with self.connect() as db:
            db.execute("UPDATE jobs SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?", (*fields.values(), job_id))

    def events(self, identity, after=0):
        self.get(identity)
        with self.connect() as db:
            return [{**dict(row), "payload": json.loads(row["payload"])} for row in
                    db.execute("SELECT * FROM events WHERE run=? AND seq>? ORDER BY seq LIMIT 500", (identity, after))]
