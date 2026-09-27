import sys

import pytest

from partdb.embeddings import OpenAIEmbeddingProvider
from partdb.errors import EmbeddingFailed, EmbeddingUnavailable


def test_offline_module_does_not_import_openai(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    from partdb import embeddings

    assert embeddings.EmbeddingProvider is not None


def test_provider_requires_key_before_importing_client(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(EmbeddingUnavailable, match="PARTDB_OPENAI_API_KEY"):
        OpenAIEmbeddingProvider(env={})


def test_provider_ignores_generic_openai_key() -> None:
    with pytest.raises(EmbeddingUnavailable, match="PARTDB_OPENAI_API_KEY"):
        OpenAIEmbeddingProvider(env={"OPENAI_API_KEY": "sk-other"})


def test_provider_passes_helper_key_to_client(monkeypatch) -> None:
    openai = pytest.importorskip("openai")
    seen = {}

    class Client:
        def __init__(self, api_key):
            seen["api_key"] = api_key

    monkeypatch.setattr(openai, "OpenAI", Client)
    OpenAIEmbeddingProvider(env={"PARTDB_OPENAI_API_KEY_CMD": "printf 'sk-cmd\\n'"})
    assert seen == {"api_key": "sk-cmd"}


def test_provider_api_errors_become_domain_errors(monkeypatch) -> None:
    openai = pytest.importorskip("openai")

    class FailingEmbeddings:
        def create(self, **_kwargs):
            raise openai.OpenAIError("rate limited")

    class FailingClient:
        embeddings = FailingEmbeddings()

        def __init__(self, api_key):
            pass

    monkeypatch.setattr(openai, "OpenAI", FailingClient)
    provider = OpenAIEmbeddingProvider(env={"PARTDB_OPENAI_API_KEY": "test-key"})

    with pytest.raises(EmbeddingFailed, match="rate limited"):
        provider.embed("resistor")
