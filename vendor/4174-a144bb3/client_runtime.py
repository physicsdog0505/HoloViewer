"""Resolve the standalone Client code root separately from local runtime data."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


CODE_ROOT = Path(__file__).resolve().parent


def client_runtime_root(
    *,
    code_root: Path = CODE_ROOT,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return the local runtime-data root used by the Client.

    Production/default behavior remains checkout-local.  A separate Client
    worktree can point at an existing authorized runtime checkout with
    PTT_CLIENT_RUNTIME_ROOT without copying databases or discovery sidecars.
    """

    env = os.environ if environ is None else environ
    raw = str(env.get("PTT_CLIENT_RUNTIME_ROOT") or "").strip()
    return Path(raw).expanduser().resolve() if raw else code_root.resolve()
