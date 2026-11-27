#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from harnesslens.benchmarks.benchmark_splits import (
    load_benchmark_split,
    supported_test_benchmarks,
)
from harnesslens.core.config import load_repo_env, repo_root
from harnesslens.evaluation.blind_test_eval import (
    BASELINE_MAX_CONCURRENCY,
    BASELINE_REPEATS,
    run_test_baseline,
    runtime_limits,
    split_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run an additive TEST baseline without entering the controller."
    )
    from harnesslens.benchmarks.cell_config import benchmark_cell
    parser.add_argument("--benchmark", required=True, type=benchmark_cell, help="Benchmark name or benchmark.toml path")
    parser.add_argument("--harness", choices=("opencode", "pi", "codex"), default="opencode")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--models-config", type=Path, help="TOML containing explicit models.execution and models.analysis")
    parser.add_argument("--agent-config", type=Path, help="Python/HTTP business-agent adapter TOML")
    parser.add_argument("--initial-harness", type=Path, help="Optional initial OpenCode directory/package; omitted means empty v0")
    parser.add_argument("--repeats", type=int, choices=(1, 2), default=BASELINE_REPEATS)
    parser.add_argument(
        "--task-id",
        action="append",
        help="Run pass@k for one or more canonical TEST tasks; omit for the full TEST split.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=repo_root())
    parser.add_argument('--train-count',type=int,help='TRAIN task count; 0 uses the entire available pool')
    parser.add_argument('--test-count',type=int,help='TEST task count; 0 uses the entire available pool')
    parser.add_argument('--domain',help='Task domain ID; all or group:<name>')
    args = parser.parse_args()
    root = args.repo_root.resolve()
    load_repo_env(root)
    from harnesslens.benchmarks.selection import configure_selection
    dataset=None
    if any(v is not None for v in (args.train_count,args.test_count,args.domain)):
        dataset={'train_count':args.train_count or 0,'test_count':args.test_count or 0,'domain':args.domain or 'all'}
    elif args.models_config:
        import tomllib
        dataset=tomllib.loads(args.models_config.read_text()).get('dataset')
    configure_selection(args.benchmark,raw=dataset,mode='test_baseline',
        run_root=None if getattr(args,'dry_run',False) else root/'runs/test_baselines'/args.run_id)

    from harnesslens.harnesses.business_agent import select_config
    select_config(args.agent_config)
    split = load_benchmark_split(args.benchmark)
    if args.dry_run:
        print(
            json.dumps(
                {
                    **split_summary(split),
                    "scope": "TEST",
                    "harness": args.harness,
                    "repeats": args.repeats,
                    "trial_count": len(args.task_id or split.test) * args.repeats,
                    "selected_test_task_ids": args.task_id or list(split.test),
                    "max_concurrency": runtime_limits(split, repeats=args.repeats)["max_concurrency"],
                    "runtime_limits": runtime_limits(split, repeats=args.repeats),
                    "model_network": "direct",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    from harnesslens.core.model_config import task_models
    task_models(args.models_config, business=bool(args.agent_config or os.environ.get("HAI_AGENT_CONFIG")),
                run_root=root / "runs/test_baselines" / args.run_id)
    result = run_test_baseline(
        repo_root=root,
        run_id=args.run_id,
        benchmark=args.benchmark,
        task_ids=args.task_id,
        repeats=args.repeats,
        harness=args.harness,
        **({"initial_harness": args.initial_harness} if args.initial_harness is not None else {}),
    )
    print(
        json.dumps(
            {
                "benchmark": result.benchmark,
                "harness": args.harness,
                "output": result.output_path,
                "metrics": result.response.metrics,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
