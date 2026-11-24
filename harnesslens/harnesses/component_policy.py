"""Per-experiment edit boundaries, independent of the benchmark and discovery."""
from __future__ import annotations

import json
import os
from typing import Mapping

from .opencode_components import EDITABLE_IDS, PROPOSAL_ONLY, component_id

ENV = "HAI_COMPONENT_POLICY"
# Behavioral fields supported by the pinned runtime. Telemetry/provider policy
# fields belong to the original proposal-only categories, not this experiment.
EXPERIMENTAL_FIELDS = frozenset({"batch_tool", "primary_tools", "continue_loop_on_deny", "mcp_timeout", "disable_paste_summary"})
DEFAULT_EXPERIMENTAL_FIELDS = frozenset({"primary_tools", "continue_loop_on_deny", "mcp_timeout"})


def normalize_policy(raw=None):
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping) or set(raw) - {"allowed", "denied", "experimental_fields"}:
        raise ValueError("components supports allowed, denied and experimental_fields")
    def names(key, default, universe, aliases=False):
        values = raw.get(key, default)
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise ValueError(f"components.{key} must be an array of names")
        values = [component_id(v) if aliases else v for v in values]
        if values == ["*"]:
            return set(universe)
        unknown = set(values) - set(universe)
        if unknown:
            raise ValueError(f"Unknown or proposal-only components.{key}: {sorted(unknown)}")
        return set(values)
    allowed = names("allowed", ["*"], EDITABLE_IDS, True)
    denied = names("denied", [], EDITABLE_IDS, True)
    experimental = names("experimental_fields", sorted(DEFAULT_EXPERIMENTAL_FIELDS), EXPERIMENTAL_FIELDS)
    return {"allowed": sorted(allowed - denied), "denied": sorted(denied),
            "experimental_fields": sorted(experimental), "proposal_only": sorted(PROPOSAL_ONLY)}


def current_policy():
    value = os.environ.get(ENV)
    return normalize_policy(json.loads(value) if value else None)


def allowed_components(business=None, *, policy=None):
    allowed = set((policy if policy is not None else current_policy())["allowed"])
    if business is not None:
        allowed &= {component_id(v) for v in business["capabilities"]["channels"]}
    return allowed


def policy_contract(business=None, *, policy=None):
    return {**(policy if policy is not None else current_policy()), "effective_allowed": sorted(allowed_components(business, policy=policy)),
            "admission": "Model discovery plus candidate runtime preflight; an allowed component is not automatically selected or verified."}


def receiver_policy(requested=None):
    """Per-request intersection without changing process-global environment."""
    server = current_policy()
    if requested is None: return server
    if not isinstance(requested, Mapping): raise ValueError("component_policy must be an object")
    request = normalize_policy({key: requested[key] for key in ("allowed", "denied", "experimental_fields") if key in requested})
    return normalize_policy({"allowed": sorted(set(server["allowed"]) & set(request["allowed"])),
        "denied": sorted(set(server["denied"]) | set(request["denied"])),
        "experimental_fields": sorted(set(server["experimental_fields"]) & set(request["experimental_fields"]))})
