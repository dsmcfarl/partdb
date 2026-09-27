import sys

import pytest

from partdb.embeddings import OpenAIEmbeddingProvider
from partdb.errors import EmbeddingFailed, EmbeddingUnavailable


def test_offline_module_does_not_import_openai(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    from partdb import embeddings

    assert embeddings.EmbeddingProvider is not None


def test_provider_requires_key_before_importing_client(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EmbeddingUnavailable, match="OPENAI_API_KEY"):
        OpenAIEmbeddingProvider()


def test_provider_api_errors_become_domain_errors(monkeypatch) -> None:
    openai = pytest.importorskip("openai")

    class FailingEmbeddings:
        def create(self, **_kwargs):
            raise openai.OpenAIError("rate limited")

    class FailingClient:
        embeddings = FailingEmbeddings()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", FailingClient)
    provider = OpenAIEmbeddingProvider()

    with pytest.raises(EmbeddingFailed, match="rate limited"):
        provider.embed("resistor")
