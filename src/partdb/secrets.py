"""Credential-helper standard: VAR if set, else the stdout of `sh -c "$VAR_CMD"`."""

import subprocess
from collections.abc import Callable, Mapping
from typing import Any

HELPER_TIMEOUT = 60  # seconds; longer than the helper's own 30 s backend timeout


class SecretError(Exception):
    """A secret could not be resolved. The message never contains the value."""


def secret_from(
    env: Mapping[str, str], var: str, run: Callable[..., Any] = subprocess.run
) -> str:
    """`var` if set and non-empty, else the stdout of `sh -c "$<var>_CMD"`.

    The command's stdout is the secret: it is never shown, not even on failure.
    """
    value = (env.get(var) or "").strip()
    if value:
        return value
    cmd_var = var + "_CMD"
    cmd = (env.get(cmd_var) or "").strip()
    if not cmd:
        raise SecretError(f"{var} or {cmd_var} must be set")
    try:
        proc = run(
            ["sh", "-c", cmd],
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=HELPER_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise SecretError(f"{cmd_var} timed out after {HELPER_TIMEOUT}s") from None
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()
        raise SecretError(
            f"{cmd_var} failed (exit {proc.returncode})"
            + (f": {detail}" if detail else "")
        )
    out = proc.stdout
    value = out.removesuffix("\n")
    if not value.strip():
        raise SecretError(f"{cmd_var} printed nothing")
    return value
