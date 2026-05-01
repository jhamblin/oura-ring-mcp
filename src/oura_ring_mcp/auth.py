"""PAT resolution. Order: env var → config file → per-call argument."""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_PATH = Path.home() / ".oura-mcp" / "config.json"
ENV_VAR = "OURA_PAT"


class PATNotConfigured(RuntimeError):
    """No Oura Personal Access Token could be resolved."""


def resolve_pat(override: str | None = None) -> str:
    if override:
        return override
    env = os.environ.get(ENV_VAR)
    if env:
        return env
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
        except json.JSONDecodeError as e:
            raise PATNotConfigured(f"{CONFIG_PATH} is not valid JSON: {e}") from e
        pat = data.get("pat")
        if pat:
            return pat
    raise PATNotConfigured(
        "No Oura PAT found. Set OURA_PAT env var, write "
        f'{{"pat": "..."}} to {CONFIG_PATH}, or pass pat=... per call. '
        "Get a token at https://cloud.ouraring.com/personal-access-tokens"
    )
