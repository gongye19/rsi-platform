"""Independent execution/analysis connections. Secrets never enter profiles."""
import os
import re
from urllib.parse import urlsplit

ROLES = ("execution", "analysis")
APIS = {"chat_completions", "responses"}


def normalize_models(raw):
    if not isinstance(raw, dict) or set(raw) != set(ROLES):
        raise ValueError("Task startup requires models.execution and models.analysis")
    result = {}
    for role in ROLES:
        row = raw[role]
        if not isinstance(row, dict) or set(row) - {"model", "api", "base_url", "base_url_env", "api_key_env", "managed_by"}:
            raise ValueError(f"Invalid models.{role} settings")
        if role == "execution" and row.get("managed_by") == "business_agent":
            if set(row) != {"managed_by"}:
                raise ValueError("Business-managed execution must be configured at the business service")
            result[role] = dict(row)
            continue
        if "managed_by" in row or not isinstance(row.get("model"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./:-]+", row["model"]):
            raise ValueError(f"models.{role}.model must be provider/model")
        if not isinstance(row.get("api"), str) or row["api"] not in APIS:
            raise ValueError(f"models.{role}.api must be chat_completions or responses")
        if bool(row.get("base_url")) == bool(row.get("base_url_env")):
            raise ValueError(f"models.{role} needs exactly one base_url or base_url_env")
        for field in ("api_key_env", "base_url_env"):
            if field in row and (not isinstance(row[field], str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", row[field])):
                raise ValueError(f"Invalid models.{role}.{field} reference")
        if not row.get("api_key_env"):
            raise ValueError(f"models.{role}.api_key_env is required")
        if row.get("base_url"):
            clean_base_url(row["base_url"])
        result[role] = dict(row)
    return result


def clean_base_url(value):
    if not isinstance(value, str):
        raise ValueError("Model base URL must be a string")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Model base URL must be HTTP(S), without credentials/query/fragment")
    value = value.rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if value.endswith(suffix):
            value = value[:-len(suffix)]
    return value


def configure_models(raw, env, *, business=False):
    """Apply a launch profile to a child environment; return public receipt."""
    models = normalize_models(raw)
    receipt = {}
    for role, row in models.items():
        prefix = "HAI_" + role.upper()
        if row.get("managed_by"):
            if not business:
                raise ValueError("business_agent execution requires agent_config")
            for suffix in ("MODEL", "BASE_URL", "API_KEY", "API"):
                env.pop(f"{prefix}_{suffix}", None)
            receipt[role] = dict(row)
            continue
        if role == "execution" and business:
            raise ValueError("HTTP/Python execution model belongs to the business agent; set managed_by=business_agent")
        base = row.get("base_url") or env.get(row.get("base_url_env"), "")
        if not base:
            raise ValueError(f"models.{role} base URL is missing from its referenced environment variable")
        key = env.get(row["api_key_env"], "").strip()
        if not key:
            raise ValueError(f"models.{role} credential is missing: {row['api_key_env']}")
        base = clean_base_url(base)
        env.update({f"{prefix}_MODEL": row["model"], f"{prefix}_BASE_URL": base,
                    f"{prefix}_API_KEY": key, f"{prefix}_API": row["api"]})
        receipt[role] = {"model": row["model"], "base_url": base, "api": row["api"], "api_key_env": row["api_key_env"]}
    # Older execution adapters consume these names; analysis never uses them
    # once its own connection has been selected.
    if not business:
        env["DEEPSEEK_API_KEY"] = env["HAI_EXECUTION_API_KEY"]
        env["DEEPSEEK_BASE_URL"] = env["HAI_EXECUTION_BASE_URL"]
        env.pop("DEEPSEEK_URL", None)
    env.pop("HAI_CRM_MODEL", None)
    env.pop("HAI_MODEL", None)
    return receipt


def connection(role, env=None):
    """Legacy fallback is only for low-level adapters, never task profiles."""
    if role not in ROLES:
        raise ValueError("Unknown model role")
    env = os.environ if env is None else env
    prefix = "HAI_" + role.upper()
    api = env.get(f"{prefix}_API", "chat_completions")
    if api not in APIS:
        raise ValueError(f"{prefix}_API must be chat_completions or responses")
    configured = any(env.get(f"{prefix}_{field}") for field in ("MODEL", "BASE_URL", "API_KEY", "API"))
    base = env.get(f"{prefix}_BASE_URL", "") if configured else (env.get("DEEPSEEK_BASE_URL") or env.get("DEEPSEEK_URL") or "https://api.deepseek.com/v1")
    return {"model": env.get(f"{prefix}_MODEL") or env.get("HAI_MODEL" if role == "analysis" else "HAI_CRM_MODEL", ""),
            "base_url": clean_base_url(base) if base else "",
            "api_key": env.get(f"{prefix}_API_KEY", "") if configured else env.get("DEEPSEEK_API_KEY", ""), "api": api}


def proxy_environment(role):
    config = connection(role)
    if not config["api_key"] or not config["base_url"]:
        raise RuntimeError(f"{role} model credential or base URL is unavailable")
    env = without_credentials(os.environ)
    env.pop("DEEPSEEK_URL", None)
    env.update(DEEPSEEK_API_KEY=config["api_key"], DEEPSEEK_BASE_URL=config["base_url"], HAI_PROXY_API=config["api"])
    if config["model"]:
        env["HAI_PROXY_MODEL"] = config["model"].split("/", 1)[-1]
    else:
        env.pop("HAI_PROXY_MODEL", None)
    return env


def task_models(path=None, *, business=False, run_root=None):
    """Direct CLI counterpart of the service's mandatory profile selection."""
    import json
    import tomllib
    from pathlib import Path
    if path:
        raw = tomllib.loads(Path(path).read_text()).get("models")
    elif os.environ.get("HAI_MODEL_CONNECTIONS"):
        receipt = json.loads(os.environ["HAI_MODEL_CONNECTIONS"])
        freeze_connections(run_root, receipt)
        return receipt
    else:
        raw = {}
        for role in ROLES:
            prefix = "HAI_" + role.upper()
            if role == "execution" and business:
                raw[role] = {"managed_by": "business_agent"}
            else:
                raw[role] = {"model": os.environ.get(prefix + "_MODEL", ""),
                             "api": os.environ.get(prefix + "_API", ""),
                             "base_url": os.environ.get(prefix + "_BASE_URL", ""),
                             "api_key_env": prefix + "_API_KEY"}
    receipt = configure_models(raw, os.environ, business=business)
    os.environ["HAI_MODEL_CONNECTIONS"] = json.dumps(receipt, sort_keys=True)
    freeze_connections(run_root, receipt)
    return receipt


def execution_model(default="deepseek/deepseek-v4-flash"):
    return connection("execution")["model"] or default


def apply_execution_provider(config):
    """Bind any native OpenCode benchmark config to the selected connection."""
    if not os.environ.get("HAI_EXECUTION_MODEL"):
        return config
    selected = connection("execution")
    provider, model = selected["model"].split("/", 1)
    original = next(iter(config["provider"].values()))
    original_model = next(iter(original["models"].values()))
    options = {**original_model.get("options", {}), **({"store": False} if selected["api"] == "responses" else {})}
    config.update(model=selected["model"], small_model=selected["model"], enabled_providers=[provider],
                  provider={provider: {**original, "npm": "@ai-sdk/openai" if selected["api"] == "responses" else "@ai-sdk/openai-compatible",
                                       "name": "Execution provider", "models": {model: {**original_model, "name": model, "options": options}}}})
    return config


def freeze_connections(run_root, receipt):
    if run_root is None:
        return
    import json
    from pathlib import Path
    from harnesslens.core.artifacts import write_json
    path = Path(run_root) / "model_connections.json"
    if path.is_file() and json.loads(path.read_text()) != receipt:
        raise ValueError("Model connections changed; choose a new run ID")
    write_json(path, receipt)


def without_credentials(env):
    markers = ("KEY", "TOKEN", "PASSWORD", "SECRET", "AUTH", "COOKIE", "CREDENTIAL")
    return {k: v for k, v in env.items() if not any(word in k.upper() for word in markers)}
