"""Unified LLM client package.

Consolidates all LLM provider interactions into a single package with
sync + async + streaming support. Replaces both agent_llm_client.py and
llm_provider.py.

Usage:
    from guideai.llm import LLMClient, LLMConfig, ProviderType

    # Sync
    client = LLMClient(LLMConfig.from_env())
    response = client.call(messages=[{"role": "user", "content": "Hello"}])

    # Async
    response = await client.acall(messages=[{"role": "user", "content": "Hello"}])

    # Streaming
    async for chunk in client.astream(messages=[{"role": "user", "content": "Hello"}]):
        print(chunk.text, end="")
"""

from guideai.llm.types import (
    LLMCallMetrics,
    LLMConfig,
    LLMError,
    LLMResponse,
    AuthenticationError,
    ModelDefinition,
    MODEL_CATALOG,
    ProviderType,
    RateLimitError,
    StreamChunk,
    StreamChunkType,
    TokenBudgetError,
    get_model,
    list_models,
)
from guideai.llm.client import LLMClient
from guideai.llm.providers.base import Provider
from guideai.llm.providers import get_provider, PROVIDER_REGISTRY

__all__ = [
    # Client
    "LLMClient",
    # Config / types
    "LLMConfig",
    "LLMResponse",
    "LLMCallMetrics",
    "StreamChunk",
    "StreamChunkType",
    # Provider
    "Provider",
    "ProviderType",
    "get_provider",
    "PROVIDER_REGISTRY",
    # Model catalog
    "ModelDefinition",
    "MODEL_CATALOG",
    "get_model",
    "list_models",
    # Errors
    "LLMError",
    "RateLimitError",
    "AuthenticationError",
    "TokenBudgetError",
]
