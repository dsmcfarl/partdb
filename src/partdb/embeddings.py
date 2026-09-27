import os
import subprocess
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from partdb.errors import EmbeddingFailed, EmbeddingUnavailable
from partdb.secrets import SecretError, secret_from

KEY_VAR = "PARTDB_OPENAI_API_KEY"


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        run: Callable[..., Any] = subprocess.run,
    ) -> None:
        try:
            key = secret_from(os.environ if env is None else env, KEY_VAR, run=run)
        except SecretError as exc:
            raise EmbeddingUnavailable(str(exc)) from None
        try:
            from openai import OpenAI, OpenAIError
        except ImportError as exc:
            raise EmbeddingUnavailable(
                "install the 'embeddings' extra to use semantic search"
            ) from exc
        self._client = OpenAI(api_key=key)
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
