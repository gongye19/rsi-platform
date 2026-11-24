import argparse
import json
import os
from pathlib import Path
import signal

from .config import ROOT, load_profile
from .store import Store


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Local HarnessLens service and job controls")
    parser.add_argument("--state-dir", type=Path, default=ROOT / "runs/service")
    sub = parser.add_subparsers(dest="command", required=True)
    api = sub.add_parser("api"); api.add_argument("--host", default="127.0.0.1"); api.add_argument("--port", type=int, default=8765)
    api.add_argument("--profiles", type=Path, default=ROOT / "configs/experiments")
    worker = sub.add_parser("worker"); worker.add_argument("--once", action="store_true")
    create = sub.add_parser("create"); create.add_argument("run_id"); create.add_argument("--profile", type=Path, required=True)
    plan = sub.add_parser("plan"); plan.add_argument("--profile", type=Path, required=True)
    sub.add_parser("list")
    for name in ("status", "start", "stop", "resume", "events"):
        p = sub.add_parser(name); p.add_argument("run_id")
    args = parser.parse_args()
    if args.command == "plan":
        profile = load_profile(args.profile)
        print(json.dumps({key: value for key, value in profile.items() if key != "environment"}, indent=2))
        return
    store = Store(args.state_dir)
    if args.command == "api":
        from .api import server
        server(store, os.environ.get("HAI_SERVICE_TOKEN", ""), args.host, args.port, args.profiles).serve_forever()
    elif args.command == "worker":
        from .worker import Worker
        engine = Worker(store)
        signal.signal(signal.SIGTERM, lambda *_: engine.shutdown.set())
        signal.signal(signal.SIGINT, lambda *_: engine.shutdown.set())
        engine.run(once=args.once)
    else:
        result = (store.create(args.run_id, args.profile) if args.command == "create" else
                  store.list() if args.command == "list" else store.get(args.run_id) if args.command == "status" else
                  store.events(args.run_id) if args.command == "events" else store.transition(args.run_id, args.command))
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
