"""Persistent configuration for Draft (endpoint + model).

Configuration is stored in ``.draft/config.json`` at the project root
and loaded with precedence: config file -> environment (``.env``) ->
defaults. The module is import-safe anywhere; ``ensure_loaded`` is
idempotent and merges the config file into the environment so
existing ``os.getenv("PROJECT_ENDPOINT")`` consumers keep working.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_LOADED = False


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    """Return the path to the persistent config file."""
    return _project_root() / ".draft" / "config.json"


@dataclass
class Config:
    """Resolved configuration values."""
    endpoint: str = ""
    model: str = "gpt-4.1-mini"


def ensure_loaded() -> None:
    """Load .env then apply .draft/config.json over the environment.

    Idempotent: only the first call performs the merge.
    """
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    load_dotenv()
    path = config_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    if data.get("endpoint"):
        os.environ["PROJECT_ENDPOINT"] = str(data["endpoint"])
    if data.get("model"):
        os.environ["MODEL_DEPLOYMENT"] = str(data["model"])


def load_config() -> Config:
    """Return the active configuration (file -> env -> defaults).

    Each key falls back independently: config file, then environment,
    then default.  A partially-populated config file (e.g. only
    ``model``) never drops values provided only in the environment.
    """
    ensure_loaded()
    data: dict[str, str] = {}
    path = config_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    return Config(
        endpoint=(data.get("endpoint") or os.getenv("PROJECT_ENDPOINT", "")).strip(),
        model=(data.get("model") or os.getenv("MODEL_DEPLOYMENT", "gpt-4.1-mini").strip()
               or "gpt-4.1-mini"),
    )


def save_config(endpoint: str | None = None, model: str | None = None) -> None:
    """Persist endpoint/model to .draft/config.json and the environment.

    Either value may be omitted; omitted values are left untouched.
    """
    ensure_loaded()
    if endpoint is not None:
        os.environ["PROJECT_ENDPOINT"] = endpoint
    if model is not None:
        os.environ["MODEL_DEPLOYMENT"] = model

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, str] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    if endpoint is not None:
        data["endpoint"] = endpoint
    if model is not None:
        data["model"] = model
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def clear_config() -> None:
    """Delete the config file and clear its environment variables."""
    path = config_path()
    if path.exists():
        path.unlink()
    os.environ.pop("PROJECT_ENDPOINT", None)
    os.environ.pop("MODEL_DEPLOYMENT", None)
