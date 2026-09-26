import sys

import pytest

from partdb.embeddings import OpenAIEmbeddingProvider
from partdb.errors import EmbeddingUnavailable


def test_offline_module_does_not_import_openai(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    from partdb import embeddings

    assert embeddings.EmbeddingProvider is not None


def test_provider_requires_key_before_importing_client(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EmbeddingUnavailable, match="OPENAI_API_KEY"):
        OpenAIEmbeddingProvider()
