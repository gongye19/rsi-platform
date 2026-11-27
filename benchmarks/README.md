# Benchmark library

The console discovers `benchmarks/<id>/benchmark.toml`. Use lowercase letters,
digits, `-` or `_`; the manifest `id` must match the directory. Adding a directory
makes it available next time **New experiment** is opened. No frontend code change is needed.

```text
benchmarks/
  team-qa/
    benchmark.toml        # required: metadata, fixed split, field names and scorer
    data/tasks.jsonl      # required for a custom JSONL benchmark; private, ignored by Git
    scorer.py             # optional custom scorer (grader = "python")
    references/           # optional private scoring material; ignored by Git
```

Custom example:

```toml
schema = "harnesslens.business-benchmark.v1"
id = "team-qa"
name = "Team QA"
tasks = "data/tasks.jsonl"
train = ["q1", "q2", "q3", "q4", "q5", "q6"]
test = ["q7", "q8"]
public_fields = ["question"]
grader = "exact"
reference_field = "answer"
```

Each JSONL row has a unique `id` and a nonempty `question`. `answer` is required
only by the exact scorer. For open questions, configure the existing Python
scorer protocol (`grader="python"`, `grader_file="scorer.py"`, optional
`grader_function`) instead. Ground truth, acceptance rules and databases remain
host-side; only `public_fields` are delivered to the agent.

Optional domains: add `domain_field="domain"` and include `domain` in
`public_fields`; each row then needs a nonempty domain value. Without this field,
the entire benchmark is one domain and the console hides the domain selector.
TRAIN and TEST IDs must be disjoint. Counts and domain options are read from
this benchmark, never hardcoded in the UI. Sampling stays inside each original
split, with fixed task IDs saved per experiment. Normal evolution needs at least
5 TRAIN tasks; small domains are not silently padded using TEST data.

Existing native adapters use a small registration manifest:

```toml
schema = "rsi.benchmark.v1"
id = "fdabench"
name = "FDABench Lite · Reports"
adapter = "fdabench"
```

The console ships with the FDABench Lite · Reports registration.
Its data may remain at the configured
external data root; registering an adapter does not download or install it.
Other native adapters remain usable through the CLI; add a registration manifest
under this directory when they are needed in the console.
FDABench exposes its public database groups. New JSONL benchmarks can use either
`--cell <id>` or the descriptor path; legacy external descriptor paths remain
supported by the CLI/API. See [adapter protocol](../docs/BENCHMARK-ADAPTERS.zh-CN.md).
