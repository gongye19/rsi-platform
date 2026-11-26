#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from harnesslens.benchmarks.cell_config import benchmark_cell, benchmark_config, supported_cell_help
from harnesslens.infrastructure.clash_proxy import configure_terminal_clash_proxy
from harnesslens.core.config import load_repo_env, repo_root
from harnesslens.evolution.controller import IterationController


def configure_cell_runtime(repo_root: Path, cell: str) -> None:
    if benchmark_config(repo_root, cell).kind == "terminal_bench":
        configure_terminal_clash_proxy()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--models-config", type=Path, help="TOML containing explicit models.execution and models.analysis")
    parser.add_argument("--agent-config", type=Path, help="Existing Python/HTTP business-agent adapter TOML")
    parser.add_argument("--initial-harness", type=Path, help="Optional initial OpenCode directory/package; omitted means an empty v0")
    parser.add_argument("--baseline-event", type=Path)
    parser.add_argument(
        "--analysis-source-run",
        help=(
            "Reuse discovery, baseline Experience, and baseline Analyzer artifacts "
            "from a run with the exact same baseline trajectories."
        ),
    )
    parser.add_argument(
        "--promotion-metric",
        choices=("pass_at_1", "pass_at_2", "mean_reward"),
        default=None,
        help="Primary paired metric that a candidate must strictly improve.",
    )
    parser.add_argument(
        "--incumbent-submission",
        type=Path,
        action="append",
        default=[],
        help=(
            "Prior TRAIN-accepted submission/final.json to revalidate as a normal "
            "candidate; may be repeated."
        ),
    )
    parser.add_argument("--harness", choices=("opencode", "pi", "codex"), default="opencode")
    parser.add_argument(
        "--cell",
        default="retail", type=benchmark_cell, help=f"benchmark cell: {supported_cell_help()}")
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
    configure_selection(args.cell,raw=dataset,mode='train',
        run_root=None if getattr(args,'dry_run',False) else root/'runs/train'/args.run_id)

    from harnesslens.harnesses.business_agent import select_config
    select_config(args.agent_config)
    from harnesslens.core.model_config import task_models
    task_models(args.models_config, business=bool(args.agent_config or os.environ.get("HAI_AGENT_CONFIG")),
                run_root=root / "runs/train" / args.run_id)
    configure_cell_runtime(root, args.cell)
    result = IterationController(
        repo_root=root,
        run_id=args.run_id,
        harness=args.harness,
        cell=args.cell,
        incumbent_submissions=tuple(args.incumbent_submission),
        promotion_metric=args.promotion_metric,
        analysis_source_run=args.analysis_source_run,
        initial_harness=args.initial_harness,
    ).run(baseline_event=args.baseline_event)
    print(json.dumps({
        "selected_version": result.selected_version,
        "submission": result.submission_path,
        "budget": result.budget,
        "cell": args.cell,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
