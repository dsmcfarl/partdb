import subprocess

import pytest

from partdb.secrets import SecretError, secret_from


def test_value_wins_and_helper_not_run() -> None:
    calls: list[object] = []
    env = {"PARTDB_OPENAI_API_KEY": " sk \n", "PARTDB_OPENAI_API_KEY_CMD": "exit 1"}
    assert (
        secret_from(env, "PARTDB_OPENAI_API_KEY", run=lambda *a, **k: calls.append(a))
        == "sk"
    )
    assert calls == []


def test_helper_used_when_value_unset() -> None:
    env = {"PARTDB_OPENAI_API_KEY_CMD": "printf 'sk-cmd\\n'"}
    assert secret_from(env, "PARTDB_OPENAI_API_KEY") == "sk-cmd"


def test_helper_failure_reports_stderr_not_stdout() -> None:
    env = {"PARTDB_OPENAI_API_KEY_CMD": "echo LEAKED; echo boom >&2; exit 3"}
    with pytest.raises(SecretError) as exc:
        secret_from(env, "PARTDB_OPENAI_API_KEY")
    assert "boom" in str(exc.value) and "LEAKED" not in str(exc.value)


def test_neither_set_names_both() -> None:
    with pytest.raises(
        SecretError, match="PARTDB_OPENAI_API_KEY or PARTDB_OPENAI_API_KEY_CMD"
    ):
        secret_from({}, "PARTDB_OPENAI_API_KEY")


def test_timeout_is_error() -> None:
    def hang(*a, **k):
        raise subprocess.TimeoutExpired(a[0], k["timeout"], output="PARTIAL")

    with pytest.raises(SecretError, match="timed out"):
        secret_from({"X_CMD": "sleep 9"}, "X", run=hang)
