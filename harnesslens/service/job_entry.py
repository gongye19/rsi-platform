"""Only the fixed public CLI entrypoints are executable by service jobs."""
import runpy
import signal
import sys
from .config import ROOT


def interrupted(*_):
    raise KeyboardInterrupt("Experiment stopped")


def main():
    entry = sys.argv[1]
    if entry not in {"run_e2e.py", "run_test_baseline.py", "run_test_candidate.py"}:
        raise ValueError("Unknown job entry")
    signal.signal(signal.SIGTERM, interrupted)
    if entry == "run_e2e.py":
        # Fail before any intelligent session/provider call if Linux policy
        # prevents the optimizer's mandatory filesystem boundary.
        from harnesslens.core.config import resolve_opencode_binary
        from harnesslens.infrastructure.process_isolation import check_editor_sandbox
        resolve_opencode_binary()
        check_editor_sandbox()
    sys.argv = [str(ROOT / entry), *sys.argv[2:]]
    runpy.run_path(str(ROOT / entry), run_name="__main__")


if __name__ == "__main__":
    main()
