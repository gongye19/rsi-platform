"""Compatibility imports for old CRM integration callers; lifecycle is shared."""
from harnesslens.evaluation.business_runtime import prepare_harness, validate_record
from harnesslens.evaluation.business_runtime import run_trial as _run_trial


def run_trial(*, repo_root, pg_port, **kwargs):
    from .adapters import CrmAdapter
    return _run_trial(adapter=CrmAdapter(repo_root), resources={"pg_port": pg_port}, **kwargs)
