import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

from .config import ROOT, load_profile, invocation


def process_identity(pid):
    if not isinstance(pid, int) or pid <= 1:
        return ""
    try:
        stat = Path(f"/proc/{pid}/stat")
        if stat.is_file():
            fields = stat.read_text().rsplit(")", 1)[1].split()
            if fields[0] in {"Z", "X"}:
                return ""
            return Path("/proc/sys/kernel/random/boot_id").read_text().strip() + ":" + fields[19]
        state = subprocess.check_output(["ps", "-o", "stat=", "-p", str(pid)], text=True).strip()
        if not state or state.startswith("Z"):
            return ""
        return subprocess.check_output(["ps", "-o", "lstart=", "-p", str(pid)], text=True).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def owned_groups(pid, expected):
    if not expected or process_identity(pid) != expected:
        return {}
    if Path("/proc/self/stat").is_file():
        processes = []
        for stat in Path("/proc").glob("[0-9]*/stat"):
            try:
                fields = stat.read_text().rsplit(")", 1)[1].split()
                processes.append((int(stat.parent.name), int(fields[1]), int(fields[2])))
            except (OSError, ValueError, IndexError):
                continue
    else:
        rows = subprocess.check_output(["ps", "-axo", "pid=,ppid=,pgid="], text=True)
        processes = [tuple(map(int, line.split())) for line in rows.splitlines() if line.strip()]
    children = {pid}
    while True:
        more = {child for child, parent, _ in processes if parent in children}
        if more <= children:
            break
        children |= more
    groups = {group for child, _, group in processes if child in children and group in children}
    return {group: process_identity(group) for group in groups}


def stop_owned(pid, expected):
    groups = owned_groups(pid, expected)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for group, token in groups.items():
            if token and process_identity(group) == token:
                try:
                    os.killpg(group, sig)
                except ProcessLookupError:
                    pass
        if sig == signal.SIGTERM and groups:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and any(process_identity(p) == token for p, token in groups.items()):
                time.sleep(0.1)


class Worker:
    def __init__(self, store):
        self.store = store
        self.shutdown = threading.Event()

    def recover(self):
        for job in self.store.list():
            if job["state"] in {"running", "stopping"}:
                if job["pid"]:
                    stop_owned(job["pid"], job["identity"])
                self.store.update(job["id"], state="interrupted", error="Worker restarted; inspect unfinished business calls before resuming")
                self.store.event(job["id"], "interrupted", {})

    def run_once(self, command_override=None):
        job = self.store.claim()
        if not job:
            return False
        identity = job["id"]
        process = None
        token = ""
        try:
            profile = load_profile(job["profile"])
            if profile["fingerprint"] != job["fingerprint"]:
                raise ValueError("Experiment profile changed; create a new run")
            argv, env = invocation(profile, identity)
            directory = self.store.directory / "jobs" / identity
            directory.mkdir(parents=True, exist_ok=True)
            # Private env_file contents and credentials never enter this manifest.
            manifest = {key: value for key, value in profile.items() if key != "environment"}
            manifest["model_connections"] = json.loads(env["HAI_MODEL_CONNECTIONS"])
            (directory / "experiment.json").write_text(json.dumps(manifest, indent=2))
            with (directory / f"attempt-{job['attempt']}.log").open("w") as log:
                process = subprocess.Popen(command_override or argv, env=env, cwd=ROOT,
                    stdout=log, stderr=log, start_new_session=True)
                token = process_identity(process.pid)
                if not token:
                    raise RuntimeError("Cannot establish owned process identity")
                self.store.update(identity, pid=process.pid, identity=token)
                self.store.event(identity, "running", {"attempt": job["attempt"]})
                previous = ""
                while process.poll() is None:
                    if self.shutdown.is_set() or self.store.get(identity)["stop"]:
                        stop_owned(process.pid, token)
                        process.wait(timeout=10)
                        state = "interrupted" if self.shutdown.is_set() else "stopped"
                        self.store.update(identity, state=state)
                        self.store.event(identity, state, {})
                        return True
                    checkpoint = ROOT / "runs/train" / identity / "controller_state.json"
                    if checkpoint.is_file():
                        value = checkpoint.read_text()
                        if value != previous:
                            previous = value
                            self.store.event(identity, "checkpoint", json.loads(value))
                    time.sleep(0.25)
                state = "succeeded" if process.returncode == 0 else "failed"
                self.store.update(identity, state=state, error="" if state == "succeeded" else "Experiment exited unsuccessfully; inspect its local log")
                self.store.event(identity, state, {"returncode": process.returncode})
        except Exception as exc:
            if process and process.poll() is None:
                stop_owned(process.pid, token)
            self.store.update(identity, state="failed", error=type(exc).__name__ + ": " + str(exc))
            self.store.event(identity, "failed", {"error_type": type(exc).__name__})
        return True

    def run(self, once=False):
        with (self.store.directory / "worker.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.recover()
            while not self.shutdown.is_set():
                did_work = self.run_once()
                if once:
                    return
                if not did_work:
                    self.shutdown.wait(0.5)
