"""Frozen tool availability; never silently fall back after a live search fails."""
import os


def web_search_enabled():
    mode = os.environ.get("HAI_FDABENCH_WEB_SEARCH", "disabled")
    if mode not in {"disabled", "live"}:
        raise ValueError("HAI_FDABENCH_WEB_SEARCH must be disabled or live")
    return mode == "live"


def tool_names():
    return ["schema", "sql", "document_search", "document_read"] + (
        ["web_search"] if web_search_enabled() else []
    )
