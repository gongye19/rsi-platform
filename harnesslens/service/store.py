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
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            for name, definition in [("origin", "TEXT NOT NULL DEFAULT 'service'"), ("read_only", "INTEGER NOT NULL DEFAULT 0")]:
                if name not in columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
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

    def create(self, identity, path, settings=None, profiles=None):
        run_id(identity)
        if settings is not None:
            import sqlite3
            if any(job['id'] == identity for job in self.list()):
                raise sqlite3.IntegrityError('Run ID already exists')
            from .settings import snapshot_profile
            from .config import ROOT
            for directory in [ROOT / "runs/train" / identity, ROOT / "runs/local_experiments" / identity]:
                if directory.exists():
                    raise ValueError("Run ID already has experiment evidence; choose a new ID")
            path = snapshot_profile(path, settings, self.directory / "profiles" / identity, profiles)
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
            if row["read_only"]:
                raise ValueError("Imported experiments are read-only; create a new experiment to run again")
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


    def sync_local_runs(self):
        """Register completed CLI runs. Their execution and timestamps stay intact."""
        from .config import ROOT
        from .history import read
        for path in (ROOT / 'runs/local_experiments').glob('*/configuration.json'):
            identity = path.parent.name
            try: run_id(identity)
            except ValueError: continue
            stage = read(path.parent / 'stage.json', {})
            result = read(path.parent / 'result.json', {})
            if stage.get('status') not in {'succeeded', 'failed', 'interrupted'}: continue
            if not result and stage.get('stage') not in {'train', 'test_initial', 'test_selected'}: continue
            config = read(path, {})
            profile = config.get('profile', '')
            if not profile: continue
            state = 'succeeded' if result else 'failed' if stage.get('status') == 'failed' else 'interrupted'
            with self.connect() as db:
                existing = db.execute('SELECT origin FROM jobs WHERE id=?', (identity,)).fetchone()
                if existing: continue
                db.execute('INSERT INTO jobs(id,profile,fingerprint,state,created,updated,attempt,origin,read_only,error) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (identity, profile, config.get('fingerprint',''), state, path.stat().st_mtime,
                     (path.parent / 'stage.json').stat().st_mtime, 1, 'cli_import', 1,
                     '' if result else '原命令行实验停止，详情见原始日志'))
            self.event(identity, 'imported', {'source': 'local_cli', 'original_evidence_preserved': True})
