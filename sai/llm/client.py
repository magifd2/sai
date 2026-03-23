"""OpenAI-compatible LLM client (targets LM Studio local server).

All calls are async via httpx.AsyncClient.
Retry logic: up to 3 attempts with exponential backoff on 429/503.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from ..utils.logging import get_logger
from .response_parser import clean_response

logger = get_logger(__name__)

_RETRY_STATUS = {429, 503}
_MAX_RETRIES = 3


@dataclass
class ChatMessage:
    role: str   # "system" | "user" | "assistant"
    content: str


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        embed_model: str,
        timeout_chat: int = 120,
        timeout_embed: int = 30,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        max_concurrent_requests: int = 4,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._embed_model = embed_model
        self._max_tokens = max_tokens
        self._temperature = temperature
        # Semaphore limits total concurrent LLM calls (chat + embed)
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout_chat, connect=10.0),
        )
        self._embed_timeout = timeout_embed

    async def chat(
        self,
        messages: list[ChatMessage],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        nonce: Optional[str] = None,
    ) -> str:
        """Send a chat completion request. Returns the response text."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens or self._max_tokens,
            "temperature": temperature if temperature is not None else self._temperature,
        }

        async with self._semaphore:
            raw = await self._post_with_retry("/chat/completions", payload)
        text = raw["choices"][0]["message"]["content"]
        return clean_response(text, nonce=nonce)

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text."""
        payload = {
            "model": self._embed_model,
            "input": text,
        }
        async with self._semaphore:
            raw = await self._post_with_retry(
            "/embeddings",
            payload,
            timeout=self._embed_timeout,
        )
        return raw["data"][0]["embedding"]

    async def health_check(self) -> bool:
        """Return True if the LLM endpoint is reachable."""
        try:
            resp = await self._client.get("/models", timeout=5.0)
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("llm.health_check_failed", error=str(exc))
            return False

    async def _post_with_retry(
        self,
        path: str,
        payload: dict[str, Any],
        timeout: Optional[int] = None,
    ) -> dict[str, Any]:
        last_exc: Optional[Exception] = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                kwargs: dict[str, Any] = {}
                if timeout is not None:
                    kwargs["timeout"] = timeout
                resp = await self._client.post(path, json=payload, **kwargs)
                if resp.status_code in _RETRY_STATUS:
                    wait = 2 ** attempt
                    logger.warning(
                        "llm.retry",
                        status=resp.status_code,
                        attempt=attempt,
                        wait=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning("llm.network_error", attempt=attempt, error=str(exc))
                await asyncio.sleep(wait)

        raise RuntimeError(
            f"LLM request failed after {_MAX_RETRIES} attempts: {last_exc}"
        )

    async def aclose(self) -> None:
        await self._client.aclose()
