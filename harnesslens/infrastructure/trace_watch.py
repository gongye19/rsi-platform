"""Incremental monitoring of terminal provider failures, excluding retry notices."""
import json
from pathlib import Path


class ProviderTraceWatch:
    def __init__(self, path):
        self.path = Path(path)
        self.offset = 0
        self.pending = b""
        self.problem = ""

    def error(self):
        if self.problem or not self.path.is_file():
            return self.problem
        if self.path.stat().st_size < self.offset:
            self.offset, self.pending = 0, b""
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            data = self.pending + stream.read()
            self.offset = stream.tell()
        lines = data.split(b"\n")
        self.pending = lines.pop()
        for line in lines:
            try:
                row = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue  # Full trace validation diagnoses malformed records.
            if not isinstance(row, dict) or row.get("event") == "upstream_retry" or not isinstance(row.get("request"), dict):
                continue
            try:
                status = int(row.get("upstream_status") or 0)
            except (ValueError, TypeError):
                status = 0
            if status >= 400 or row.get("response") is None:
                self.problem = f"provider request failed: HTTP {status or 502}; see retained API trace"
                break
        return self.problem
