# Harness library

Place reusable inputs under `harnesses/<name>/`. The console reads this directory
when opening **New experiment**. Select **Empty Harness** to start with no custom
overlay. Keep credentials and installed dependencies outside this directory.

```text
harnesses/
  business-agent/
    project/
      AGENTS.md
      .opencode/
        skills/<skill-name>/SKILL.md
    home/                       # optional OpenCode home configuration
  exp-<generated-id>/            # created when an experiment starts
    library.json                # versions and selected final Harness
    versions/
      v0/harness-<sha256>.json
      candidate-01/harness-<sha256>.json
```

A manually copied project overlay may also sit directly under `<name>/`, or use
a previously exported `package.json` instead of project/home folders. Generated
packages contain the complete workspace plus manifest; they can be selected as
the initial Harness of a later experiment. The original input is never overwritten.

The service and `run_e2e.py` save the starting Harness and subsequent frozen
candidate snapshots locally. Rejected candidates stay available for inspection;
only the actual final selection is marked **Selected**. Concurrent writes use a
local lock and atomic index updates. Runtime evidence and scores remain under
`runs/`; the library stores reusable configurations only.

Library inputs/outputs are ignored by Git. Only this README is committed. Copy
your business Harness into this directory on the server; pushing the platform
never uploads business configuration or generated versions. Legacy explicit
initial-Harness paths remain supported by existing CLI/profile configurations.
