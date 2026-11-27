# Adapted from the earlier RSI Platform FDABench integration; standalone implementation.
#!/usr/bin/env python3
"""Solver-side CLI. Its scoped local token grants tools, never reference data."""

import argparse
import json
from pathlib import Path
import urllib.request


def main():
    cfg = json.loads(Path(__file__).with_name("endpoint.json").read_text())
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "tool",
        choices=cfg.get("tools_available", ["schema", "sql", "document_search", "document_read", "web_search"]),
    )
    ap.add_argument("value", nargs="?", default="")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--page", type=int, default=1)
    args = ap.parse_args()
    body = json.dumps(
        {
            "tool": args.tool,
            "value": args.value,
            "limit": args.limit,
            "page": args.page,
            "trial_id": Path(__file__).resolve().parents[2].name,
        }
    ).encode()
    req = urllib.request.Request(
        cfg["url"],
        body,
        {"Authorization": "Bearer " + cfg["token"], "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=100) as response:
        result = json.load(response)
    print(json.dumps(result, ensure_ascii=False, default=lambda x: repr(x)))
    raise SystemExit(1 if result.get("status") == "error" else 0)


if __name__ == "__main__":
    main()
