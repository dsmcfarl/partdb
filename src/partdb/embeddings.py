import os
from typing import Protocol

from partdb.errors import EmbeddingUnavailable


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class OpenAIEmbeddingProvider:
    def __init__(self) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            raise EmbeddingUnavailable("OPENAI_API_KEY is not configured")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise EmbeddingUnavailable(
                "install the 'embeddings' extra to use semantic search"
            ) from exc
        self._client = OpenAI()

    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings.create(
            input=text.replace("\n", " ")[:8191],
            model="text-embedding-3-small",
        )
        return response.data[0].embedding
