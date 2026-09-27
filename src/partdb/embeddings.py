import os
from typing import Protocol

from partdb.errors import EmbeddingFailed, EmbeddingUnavailable


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class OpenAIEmbeddingProvider:
    def __init__(self) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            raise EmbeddingUnavailable("OPENAI_API_KEY is not configured")
        try:
            from openai import OpenAI, OpenAIError
        except ImportError as exc:
            raise EmbeddingUnavailable(
                "install the 'embeddings' extra to use semantic search"
            ) from exc
        self._client = OpenAI()
        self._error = OpenAIError

    def embed(self, text: str) -> list[float]:
        try:
            response = self._client.embeddings.create(
                input=text.replace("\n", " ")[:8191],
                model="text-embedding-3-small",
            )
        except self._error as exc:
            raise EmbeddingFailed(f"OpenAI embedding request failed: {exc}") from exc
        return response.data[0].embedding
