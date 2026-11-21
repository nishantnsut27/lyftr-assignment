import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm  # noqa: E402
from litellm.caching.caching import Cache  # noqa: E402
from litellm.caching.disk_cache import DiskCache  # noqa: E402
from litellm.types.utils import ModelResponse  # noqa: E402

from app.config import Settings  # noqa: E402
from app.errors import InferenceFailed, ProvidersUnavailable  # noqa: E402

litellm.suppress_debug_info = True
litellm.set_verbose = False
litellm.turn_off_message_logging = True
for logger_name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy"):
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)
Completion = Callable[..., Awaitable[ModelResponse]]
LLMMessage = dict[str, str]


@dataclass(frozen=True)
class InferenceResult:
    reply: str
    input_tokens: int
    output_tokens: int
    model: str
    resolution_source: Literal["LIVE_INFERENCE", "LLM_CACHE"]
    key_id: str | None
    fallback_attempts: int


class InferenceGateway(Protocol):
    async def infer(
        self, messages: list[LLMMessage], simulated_failures: dict[str, int]
    ) -> InferenceResult: ...

    def check_cache_health(self) -> bool: ...

    def close(self) -> None: ...


def is_fallback_failure(error: Exception) -> bool:
    if isinstance(error, (litellm.RateLimitError, litellm.ServiceUnavailableError)):
        return True
    status = getattr(error, "status_code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status <= 599):
        return True
    # Providers also report quota exhaustion as 400/403; inspect only to classify, never log it.
    return any(
        marker in str(error).lower()
        for marker in (
            "insufficient_quota",
            "quota exceeded",
            "quota exhausted",
            "exceeded your quota",
        )
    )


def completion_result(
    response: ModelResponse,
    model: str,
    source: Literal["LIVE_INFERENCE", "LLM_CACHE"],
    key_id: str | None,
    failures: int,
) -> InferenceResult:
    if not isinstance(response, ModelResponse) or not response.choices or response.usage is None:
        raise InferenceFailed
    message = getattr(response.choices[0], "message", None)
    content = getattr(message, "content", None)
    input_tokens = getattr(response.usage, "prompt_tokens", None)
    output_tokens = getattr(response.usage, "completion_tokens", None)
    if (
        not isinstance(content, str)
        or not content.strip()
        or type(input_tokens) is not int
        or type(output_tokens) is not int
        or input_tokens < 0
        or output_tokens < 0
    ):
        raise InferenceFailed
    return InferenceResult(content, input_tokens, output_tokens, model, source, key_id, failures)


class LiteLLMGateway:
    def __init__(self, settings: Settings, completion: Completion | None = None) -> None:
        self.settings = settings
        self._completion = completion or litellm.acompletion
        settings.llm_cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache = Cache(type="disk", disk_cache_dir=str(settings.llm_cache_dir))
        self._closed = False
        self._close_cache_connection()

    def _close_cache_connection(self) -> None:
        # diskcache connections are thread-local; each worker must close its own connection.
        if isinstance(self.cache.cache, DiskCache):
            self.cache.cache.disk_cache.close()

    def check_cache_health(self) -> bool:
        if self._closed or self.cache.type != "disk" or not isinstance(self.cache.cache, DiskCache):
            return False
        disk = self.cache.cache.disk_cache
        try:
            with disk.transact():
                disk.set("__lyftr_health__", True)
                healthy = disk.get("__lyftr_health__") is True
                disk.delete("__lyftr_health__")
            return healthy
        except Exception:
            logger.warning("llm_cache_unavailable")
            return False
        finally:
            self._close_cache_connection()

    def _cache_arguments(self, messages: list[LLMMessage]) -> dict[str, Any]:
        return {"model": self.settings.llm_model, "messages": messages}

    def _read_cache(self, messages: list[LLMMessage]) -> InferenceResult | None:
        try:
            cached = self.cache.get_cache(**self._cache_arguments(messages))
            if cached is None:
                return None
            usage = cached.get("usage") if isinstance(cached, dict) else None
            if not isinstance(usage, dict) or any(
                type(usage.get(field)) is not int or usage[field] < 0
                for field in ("prompt_tokens", "completion_tokens")
            ):
                raise InferenceFailed
            return completion_result(
                ModelResponse(**cached), self.settings.llm_model, "LLM_CACHE", None, 0
            )
        except Exception:
            logger.warning("llm_cache_read_failed")
            return None
        finally:
            self._close_cache_connection()

    def _write_cache(self, result: InferenceResult, messages: list[LLMMessage]) -> None:
        try:
            # Cache the validated reply and usage without provider-only fields.
            completion = {
                "model": result.model,
                "choices": [{"message": {"role": "assistant", "content": result.reply}}],
                "usage": {
                    "prompt_tokens": result.input_tokens,
                    "completion_tokens": result.output_tokens,
                },
            }
            self.cache.add_cache(completion, **self._cache_arguments(messages))
        except Exception:
            logger.warning("llm_cache_write_failed")
        finally:
            self._close_cache_connection()

    async def infer(
        self, messages: list[LLMMessage], simulated_failures: dict[str, int]
    ) -> InferenceResult:
        # Simulation must reach the key loop even when this prompt already has a cached answer.
        if not simulated_failures:
            cached = await asyncio.to_thread(self._read_cache, messages)
            if cached is not None:
                return cached

        failed_keys = 0
        for index, key in enumerate(self.settings.api_keys, start=1):
            key_id = f"key_{index}"
            if key_id in simulated_failures or "*" in simulated_failures:
                failed_keys += 1
                continue
            try:
                async with asyncio.timeout(self.settings.llm_timeout_seconds):
                    response = await self._completion(
                        model=self.settings.llm_model,
                        messages=messages,
                        api_key=key.get_secret_value(),
                        temperature=0,
                        max_tokens=self.settings.llm_max_tokens,
                        timeout=self.settings.llm_timeout_seconds,
                        num_retries=0,
                        caching=False,
                    )
            except Exception as error:
                if is_fallback_failure(error):
                    failed_keys += 1
                    continue
                raise InferenceFailed from None

            result = completion_result(
                response, self.settings.llm_model, "LIVE_INFERENCE", key_id, failed_keys
            )
            await asyncio.to_thread(self._write_cache, result, messages)
            return result

        raise ProvidersUnavailable

    def close(self) -> None:
        self._closed = True
        self._close_cache_connection()
