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
from harnesslens.infrastructure.rootless_docker import DEFAULT_DOCKER_HOST
from harnesslens.core.config import load_repo_env, repo_root
from harnesslens.evaluation.blind_test_eval import (
    BASELINE_REPEATS,
    run_test_candidate,
    runtime_limits,
    split_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run pass@k on a HarnessLens submitted candidate over a canonical TEST split."
    )
    from harnesslens.benchmarks.cell_config import benchmark_cell
    parser.add_argument("--benchmark", required=True, type=benchmark_cell, help="Benchmark name or benchmark.toml path")
    parser.add_argument("--harness", choices=("opencode", "pi", "codex"), default="opencode")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--models-config", type=Path, help="TOML containing explicit models.execution and models.analysis")
    parser.add_argument("--agent-config", type=Path, help="Python/HTTP business-agent adapter TOML")
    parser.add_argument("--patch-json", required=True, type=Path)
    parser.add_argument("--patch-descs-json", type=Path)
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--base-version", default="v0")
    parser.add_argument("--retrieval-config", default="bm25")
    parser.add_argument("--repeats", type=int, choices=(1, 2), default=BASELINE_REPEATS)
    parser.add_argument(
        "--max-concurrency",
        type=int,
        help="Override TEST rollout concurrency without changing tasks, repeats, or harness.",
    )
    parser.add_argument(
        "--task-id",
        action="append",
        help="Run pass@k for one or more canonical TEST tasks; omit for the full TEST split.",
    )
    parser.add_argument("--docker-host", default=DEFAULT_DOCKER_HOST)
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
    configure_selection(args.benchmark,raw=dataset,mode='test_candidate',
        run_root=None if getattr(args,'dry_run',False) else root/'runs/test_candidates'/args.run_id)

    from harnesslens.harnesses.business_agent import select_config
    select_config(args.agent_config)
    split = load_benchmark_split(args.benchmark)
    if split.cell == "terminal_bench":
        os.environ["DOCKER_HOST"] = args.docker_host
    if args.dry_run:
        print(
            json.dumps(
                {
                    **split_summary(split),
                    "scope": "TEST",
                    "harness": args.harness,
                    "base_version": args.base_version,
                    "candidate_label": args.candidate_label,
                    "patch_json": str(args.patch_json.resolve()),
                    "patch_descs_json": (
                        str(args.patch_descs_json.resolve())
                        if args.patch_descs_json
                        else None
                    ),
                    "repeats": args.repeats,
                    "trial_count": len(args.task_id or split.test) * args.repeats,
                    "selected_test_task_ids": args.task_id or list(split.test),
                    "runtime_limits": runtime_limits(split, repeats=args.repeats),
                    "max_concurrency": (
                        min(
                            runtime_limits(split, repeats=args.repeats)["max_concurrency"],
                            args.max_concurrency,
                        )
                        if args.max_concurrency
                        else runtime_limits(split, repeats=args.repeats)["max_concurrency"]
                    ),
                    "retrieval_config": (
                        args.retrieval_config
                        if split.cell == "banking_knowledge"
                        else None
                    ),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    from harnesslens.core.model_config import task_models
    task_models(args.models_config, business=bool(args.agent_config or os.environ.get("HAI_AGENT_CONFIG")),
                run_root=root / "runs/test_candidates" / args.run_id)
    result = run_test_candidate(
        repo_root=root,
        run_id=args.run_id,
        benchmark=args.benchmark,
        patch_json=args.patch_json,
        patch_descs_json=args.patch_descs_json,
        candidate_label=args.candidate_label,
        base_version=args.base_version,
        retrieval_config=args.retrieval_config,
        task_ids=args.task_id,
        max_concurrency=args.max_concurrency,
        repeats=args.repeats,
        harness=args.harness,
    )
    print(
        json.dumps(
            {
                "benchmark": result.benchmark,
                "harness": args.harness,
                "harness_version": result.harness_version,
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
