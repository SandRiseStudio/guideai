"""LLM Provider abstraction layer for multi-provider model support.

Supports OpenAI, Anthropic, local models, OpenRouter, and other frontier model providers.
Follows behavior_externalize_configuration for all credentials and settings.

BCI Real LLM Integration (Epic 6/Epic 8):
- Token budget enforcement per request
- Retry logic with exponential backoff
- Comprehensive OpenAI model support
- TestProvider retained for local development
"""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="LLMProvider")


# OpenAI Model Catalog with context limits and pricing (synced with config/settings.py)
# Pricing is in USD per 1M tokens, as of January 2025
OPENAI_MODEL_LIMITS = {
    # GPT-4o series
    "gpt-4o": {"max_context": 128000, "max_output": 16384, "input_price": 2.50, "output_price": 10.00},
    "gpt-4o-2024-11-20": {"max_context": 128000, "max_output": 16384, "input_price": 2.50, "output_price": 10.00},
    "gpt-4o-2024-08-06": {"max_context": 128000, "max_output": 16384, "input_price": 2.50, "output_price": 10.00},
    "gpt-4o-2024-05-13": {"max_context": 128000, "max_output": 4096, "input_price": 5.00, "output_price": 15.00},
    "gpt-4o-mini": {"max_context": 128000, "max_output": 16384, "input_price": 0.15, "output_price": 0.60},
    "gpt-4o-mini-2024-07-18": {"max_context": 128000, "max_output": 16384, "input_price": 0.15, "output_price": 0.60},
    # o1 reasoning models (higher pricing for reasoning tokens)
    "o1": {"max_context": 200000, "max_output": 100000, "input_price": 15.00, "output_price": 60.00},
    "o1-2024-12-17": {"max_context": 200000, "max_output": 100000, "input_price": 15.00, "output_price": 60.00},
    "o1-preview": {"max_context": 128000, "max_output": 32768, "input_price": 15.00, "output_price": 60.00},
    "o1-preview-2024-09-12": {"max_context": 128000, "max_output": 32768, "input_price": 15.00, "output_price": 60.00},
    "o1-mini": {"max_context": 128000, "max_output": 65536, "input_price": 3.00, "output_price": 12.00},
    "o1-mini-2024-09-12": {"max_context": 128000, "max_output": 65536, "input_price": 3.00, "output_price": 12.00},
    # o3-mini
    "o3-mini": {"max_context": 200000, "max_output": 100000, "input_price": 1.10, "output_price": 4.40},
    "o3-mini-2025-01-31": {"max_context": 200000, "max_output": 100000, "input_price": 1.10, "output_price": 4.40},
    # GPT-4 Turbo
    "gpt-4-turbo": {"max_context": 128000, "max_output": 4096, "input_price": 10.00, "output_price": 30.00},
    "gpt-4-turbo-2024-04-09": {"max_context": 128000, "max_output": 4096, "input_price": 10.00, "output_price": 30.00},
    "gpt-4-turbo-preview": {"max_context": 128000, "max_output": 4096, "input_price": 10.00, "output_price": 30.00},
    "gpt-4-0125-preview": {"max_context": 128000, "max_output": 4096, "input_price": 10.00, "output_price": 30.00},
    "gpt-4-1106-preview": {"max_context": 128000, "max_output": 4096, "input_price": 10.00, "output_price": 30.00},
    # GPT-4 original
    "gpt-4": {"max_context": 8192, "max_output": 8192, "input_price": 30.00, "output_price": 60.00},
    "gpt-4-0613": {"max_context": 8192, "max_output": 8192, "input_price": 30.00, "output_price": 60.00},
    "gpt-4-32k": {"max_context": 32768, "max_output": 32768, "input_price": 60.00, "output_price": 120.00},
    "gpt-4-32k-0613": {"max_context": 32768, "max_output": 32768, "input_price": 60.00, "output_price": 120.00},
    # GPT-3.5 Turbo
    "gpt-3.5-turbo": {"max_context": 16385, "max_output": 4096, "input_price": 0.50, "output_price": 1.50},
    "gpt-3.5-turbo-0125": {"max_context": 16385, "max_output": 4096, "input_price": 0.50, "output_price": 1.50},
    "gpt-3.5-turbo-1106": {"max_context": 16385, "max_output": 4096, "input_price": 1.00, "output_price": 2.00},
    "gpt-3.5-turbo-16k": {"max_context": 16385, "max_output": 4096, "input_price": 3.00, "output_price": 4.00},
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> Dict[str, float]:
    """Calculate the estimated cost for a request.

    Args:
        model: The model name (e.g., "gpt-4o")
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens

    Returns:
        Dict with input_cost_usd, output_cost_usd, and total_cost_usd
    """
    model_info = OPENAI_MODEL_LIMITS.get(model, {})
    input_price = model_info.get("input_price", 0.0)  # USD per 1M tokens
    output_price = model_info.get("output_price", 0.0)  # USD per 1M tokens

    input_cost = (input_tokens / 1_000_000) * input_price
    output_cost = (output_tokens / 1_000_000) * output_price

    return {
        "input_cost_usd": round(input_cost, 6),
        "output_cost_usd": round(output_cost, 6),
        "total_cost_usd": round(input_cost + output_cost, 6),
    }


class ProviderType(str, Enum):
    """Supported LLM provider types."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"
    LOCAL = "local"
    OLLAMA = "ollama"
    TOGETHER = "together"
    GROQ = "groq"
    FIREWORKS = "fireworks"
    AZURE_OPENAI = "azure_openai"
    BEDROCK = "bedrock"
    VERTEX = "vertex"
    TEST = "test"


@dataclass
class LLMConfig:
    """Configuration for LLM provider.

    All credentials should be loaded from environment variables per behavior_externalize_configuration.
    """

    provider: ProviderType = ProviderType.OPENAI
    model: str = "gpt-4o"
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 1.0
    timeout: float = 120.0
    max_retries: int = 3
    retry_delay: float = 1.0  # Initial delay for exponential backoff
    extra_params: Dict[str, Any] = field(default_factory=dict)

    # Token budget enforcement (per-request limits)
    token_budget_enabled: bool = True
    token_budget_per_request: int = 50000  # Total tokens (input + output) per request
    token_budget_warning_threshold: float = 0.8  # Warn at 80% of budget

    @classmethod
    def from_env(cls, provider: Optional[ProviderType] = None) -> "LLMConfig":
        """Load configuration from environment variables.

        Environment variables:
        - GUIDEAI_LLM_PROVIDER: openai, anthropic, openrouter, local, etc.
        - GUIDEAI_LLM_MODEL: Model identifier (e.g., gpt-4o, claude-3-5-sonnet)
        - GUIDEAI_LLM_API_KEY: API key for the provider
        - GUIDEAI_LLM_API_BASE: Optional custom API base URL
        - GUIDEAI_LLM_MAX_TOKENS: Maximum tokens in response
        - GUIDEAI_LLM_TEMPERATURE: Sampling temperature
        - GUIDEAI_LLM_TIMEOUT: Request timeout in seconds

        Provider-specific environment variables:
        - OPENAI_API_KEY: OpenAI API key
        - ANTHROPIC_API_KEY: Anthropic API key
        - OPENROUTER_API_KEY: OpenRouter API key
        - TOGETHER_API_KEY: Together AI API key
        - GROQ_API_KEY: Groq API key
        - FIREWORKS_API_KEY: Fireworks AI API key
        - AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT: Azure OpenAI
        - OLLAMA_HOST: Ollama base URL (default: http://localhost:11434)
        """
        provider_str = os.environ.get("GUIDEAI_LLM_PROVIDER", "openai").lower()
        resolved_provider = provider or ProviderType(provider_str)

        # Default models per provider
        default_models = {
            ProviderType.OPENAI: "gpt-4o",
            ProviderType.ANTHROPIC: "claude-3-5-sonnet-20241022",
            ProviderType.OPENROUTER: "anthropic/claude-3.5-sonnet",
            ProviderType.LOCAL: "local-model",
            ProviderType.OLLAMA: "llama3.2",
            ProviderType.TOGETHER: "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            ProviderType.GROQ: "llama-3.3-70b-versatile",
            ProviderType.FIREWORKS: "accounts/fireworks/models/llama-v3p3-70b-instruct",
            ProviderType.AZURE_OPENAI: "gpt-4o",
            ProviderType.BEDROCK: "anthropic.claude-3-5-sonnet-20241022-v2:0",
            ProviderType.VERTEX: "claude-3-5-sonnet-v2@20241022",
            ProviderType.TEST: "test-model",
        }

        # Provider-specific API key resolution
        api_key = os.environ.get("GUIDEAI_LLM_API_KEY")
        if not api_key:
            key_env_map = {
                ProviderType.OPENAI: "OPENAI_API_KEY",
                ProviderType.ANTHROPIC: "ANTHROPIC_API_KEY",
                ProviderType.OPENROUTER: "OPENROUTER_API_KEY",
                ProviderType.TOGETHER: "TOGETHER_API_KEY",
                ProviderType.GROQ: "GROQ_API_KEY",
                ProviderType.FIREWORKS: "FIREWORKS_API_KEY",
                ProviderType.AZURE_OPENAI: "AZURE_OPENAI_API_KEY",
            }
            api_key = os.environ.get(key_env_map.get(resolved_provider, ""))

        # Provider-specific base URL resolution
        api_base = os.environ.get("GUIDEAI_LLM_API_BASE")
        if not api_base:
            base_url_map = {
                ProviderType.OPENROUTER: "https://openrouter.ai/api/v1",
                ProviderType.TOGETHER: "https://api.together.xyz/v1",
                ProviderType.GROQ: "https://api.groq.com/openai/v1",
                ProviderType.FIREWORKS: "https://api.fireworks.ai/inference/v1",
                ProviderType.OLLAMA: os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
                ProviderType.AZURE_OPENAI: os.environ.get("AZURE_OPENAI_ENDPOINT"),
            }
            api_base = base_url_map.get(resolved_provider)

        return cls(
            provider=resolved_provider,
            model=os.environ.get("GUIDEAI_LLM_MODEL", default_models.get(resolved_provider, "gpt-4o")),
            api_key=api_key,
            api_base=api_base,
            max_tokens=int(os.environ.get("GUIDEAI_LLM_MAX_TOKENS", "4096")),
            temperature=float(os.environ.get("GUIDEAI_LLM_TEMPERATURE", "0.7")),
            timeout=float(os.environ.get("GUIDEAI_LLM_TIMEOUT", "120")),
            max_retries=int(os.environ.get("GUIDEAI_LLM_MAX_RETRIES", "3")),
            retry_delay=float(os.environ.get("GUIDEAI_LLM_RETRY_DELAY", "1.0")),
            token_budget_enabled=os.environ.get("GUIDEAI_LLM_TOKEN_BUDGET_ENABLED", "true").lower() == "true",
            token_budget_per_request=int(os.environ.get("GUIDEAI_LLM_TOKEN_BUDGET", "50000")),
            token_budget_warning_threshold=float(os.environ.get("GUIDEAI_LLM_TOKEN_BUDGET_WARN", "0.8")),
        )


@dataclass
class LLMMessage:
    """A single message in the conversation."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMRequest:
    """Request to an LLM provider."""

    messages: List[LLMMessage]
    model: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stop: Optional[List[str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    content: str
    model: str
    provider: ProviderType
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Token budget tracking
    token_budget_used: int = 0  # Total tokens used against budget
    token_budget_remaining: int = 0  # Remaining budget after request
    token_budget_warning: bool = False  # True if approaching/exceeding budget

    # Cost estimation (USD)
    estimated_cost_usd: float = 0.0  # Total estimated cost
    input_cost_usd: float = 0.0  # Cost for input tokens
    output_cost_usd: float = 0.0  # Cost for output tokens


class LLMProviderError(Exception):
    """Base error for LLM provider operations."""

    def __init__(
        self,
        message: str,
        provider: Optional[ProviderType] = None,
        status_code: Optional[int] = None,
        raw_error: Optional[Any] = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.raw_error = raw_error


class LLMRateLimitError(LLMProviderError):
    """Raised when rate limited by provider."""

    pass


class LLMAuthenticationError(LLMProviderError):
    """Raised when authentication fails."""

    pass


class TokenBudgetExceededError(LLMProviderError):
    """Raised when a request would exceed the token budget."""

    def __init__(
        self,
        message: str,
        budget: int,
        estimated_tokens: int,
        provider: Optional[ProviderType] = None,
    ):
        super().__init__(message, provider=provider)
        self.budget = budget
        self.estimated_tokens = estimated_tokens


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            request: The LLM request with messages and parameters.

        Returns:
            LLMResponse with the generated content and metadata.

        Raises:
            LLMProviderError: If the request fails.
            LLMRateLimitError: If rate limited.
            LLMAuthenticationError: If authentication fails.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is available and configured."""
        pass

    @property
    def provider_type(self) -> ProviderType:
        """Return the provider type."""
        return self.config.provider


class OpenAIProvider(LLMProvider):
    """OpenAI API provider supporting GPT-4, GPT-4o, o1, o3-mini, etc.

    Features:
    - Token budget enforcement per request
    - Retry with exponential backoff for transient errors
    - Comprehensive model support (see OPENAI_MODEL_LIMITS)
    - Cost-aware token tracking
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client: Optional[Any] = None

    def _get_client(self) -> Any:
        """Lazily initialize OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI

                kwargs: Dict[str, Any] = {}
                if self.config.api_key:
                    kwargs["api_key"] = self.config.api_key
                if self.config.api_base:
                    kwargs["base_url"] = self.config.api_base
                kwargs["timeout"] = self.config.timeout
                # Let us handle retries for token budget tracking
                kwargs["max_retries"] = 0

                self._client = OpenAI(**kwargs)
            except ImportError as exc:
                raise LLMProviderError(
                    "OpenAI SDK not installed. Run: pip install openai",
                    provider=ProviderType.OPENAI,
                ) from exc
        return self._client

    def _estimate_input_tokens(self, messages: List[Dict[str, str]], model: str) -> int:
        """Estimate input tokens for budget checking before API call.

        Uses a conservative estimate: ~1.3 tokens per word for English text.
        For more accurate estimates, use tiktoken library.
        """
        total_chars = sum(len(msg.get("content", "")) for msg in messages)
        # Rough estimate: 4 chars per token average, with overhead for message structure
        estimated = int(total_chars / 3.5) + (len(messages) * 4)  # ~4 tokens per message overhead
        return estimated

    def _get_model_limits(self, model: str) -> Dict[str, int]:
        """Get context and output limits for a model."""
        return OPENAI_MODEL_LIMITS.get(model, {"max_context": 128000, "max_output": 4096})

    def _check_token_budget(
        self,
        messages: List[Dict[str, str]],
        model: str,
        max_tokens: int,
    ) -> tuple[int, bool]:
        """Check if request fits within token budget.

        Returns:
            Tuple of (estimated_total_tokens, is_warning)

        Raises:
            TokenBudgetExceededError: If estimated tokens exceed budget.
        """
        if not self.config.token_budget_enabled:
            return (0, False)

        estimated_input = self._estimate_input_tokens(messages, model)
        estimated_total = estimated_input + max_tokens  # max_tokens is max output

        budget = self.config.token_budget_per_request
        warning_threshold = budget * self.config.token_budget_warning_threshold

        if estimated_total > budget:
            raise TokenBudgetExceededError(
                f"Estimated tokens ({estimated_total:,}) exceeds budget ({budget:,}). "
                f"Reduce input size or max_tokens parameter.",
                budget=budget,
                estimated_tokens=estimated_total,
                provider=ProviderType.OPENAI,
            )

        is_warning = estimated_total > warning_threshold
        if is_warning:
            logger.warning(
                f"Token budget warning: estimated {estimated_total:,} tokens "
                f"({estimated_total/budget*100:.1f}% of {budget:,} budget)"
            )

        return (estimated_total, is_warning)

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate response using OpenAI API with token budget enforcement and retry logic."""
        start_time = time.perf_counter()
        client = self._get_client()

        model = request.model or self.config.model
        max_tokens = request.max_tokens or self.config.max_tokens
        temperature = request.temperature if request.temperature is not None else self.config.temperature

        # Apply model-specific limits
        model_limits = self._get_model_limits(model)
        max_tokens = min(max_tokens, model_limits["max_output"])

        messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]

        # Check token budget before making API call
        estimated_tokens, budget_warning = self._check_token_budget(messages, model, max_tokens)

        # Retry loop with exponential backoff
        last_error: Optional[Exception] = None
        retry_delay = self.config.retry_delay

        for attempt in range(self.config.max_retries + 1):
            try:
                # Handle o1/o3 models which don't support temperature
                create_kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "max_completion_tokens" if model.startswith(("o1", "o3")) else "max_tokens": max_tokens,
                }

                # o1/o3 models don't support temperature, top_p, stop
                if not model.startswith(("o1", "o3")):
                    create_kwargs["temperature"] = temperature
                    create_kwargs["top_p"] = request.top_p or self.config.top_p
                    if request.stop:
                        create_kwargs["stop"] = request.stop

                response = client.chat.completions.create(**create_kwargs)

                latency_ms = (time.perf_counter() - start_time) * 1000
                choice = response.choices[0]
                usage = response.usage

                input_tokens = usage.prompt_tokens if usage else 0
                output_tokens = usage.completion_tokens if usage else 0
                total_tokens = usage.total_tokens if usage else 0

                # Calculate budget tracking
                budget = self.config.token_budget_per_request
                budget_remaining = max(0, budget - total_tokens) if self.config.token_budget_enabled else 0

                # Calculate cost estimation
                cost_info = calculate_cost(model, input_tokens, output_tokens)

                return LLMResponse(
                    content=choice.message.content or "",
                    model=response.model,
                    provider=ProviderType.OPENAI,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                    finish_reason=choice.finish_reason,
                    raw_response=response.model_dump() if hasattr(response, "model_dump") else None,
                    token_budget_used=total_tokens,
                    token_budget_remaining=budget_remaining,
                    token_budget_warning=budget_warning or (total_tokens > budget * self.config.token_budget_warning_threshold),
                    estimated_cost_usd=cost_info["total_cost_usd"],
                    input_cost_usd=cost_info["input_cost_usd"],
                    output_cost_usd=cost_info["output_cost_usd"],
                    metadata={
                        "attempt": attempt + 1,
                        "estimated_tokens": estimated_tokens,
                        "model_limits": model_limits,
                    },
                )
            except Exception as exc:
                exc_str = str(exc).lower()
                last_error = exc

                # Don't retry auth errors
                if "authentication" in exc_str or "401" in exc_str or "invalid_api_key" in exc_str:
                    raise LLMAuthenticationError(str(exc), provider=ProviderType.OPENAI, raw_error=exc)

                # Retry on rate limits and transient errors
                if attempt < self.config.max_retries:
                    if "rate_limit" in exc_str or "429" in exc_str:
                        logger.warning(f"Rate limited (attempt {attempt + 1}/{self.config.max_retries + 1}), "
                                      f"retrying in {retry_delay:.1f}s...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    if "timeout" in exc_str or "connection" in exc_str or "500" in exc_str or "503" in exc_str:
                        logger.warning(f"Transient error (attempt {attempt + 1}/{self.config.max_retries + 1}), "
                                      f"retrying in {retry_delay:.1f}s: {exc}")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue

                # Final error handling
                if "rate_limit" in exc_str or "429" in exc_str:
                    raise LLMRateLimitError(str(exc), provider=ProviderType.OPENAI, raw_error=exc)
                raise LLMProviderError(str(exc), provider=ProviderType.OPENAI, raw_error=exc)

        # Should not reach here, but handle just in case
        raise LLMProviderError(
            f"Failed after {self.config.max_retries + 1} attempts: {last_error}",
            provider=ProviderType.OPENAI,
            raw_error=last_error,
        )

    def is_available(self) -> bool:
        """Check if OpenAI is configured."""
        return bool(self.config.api_key or os.environ.get("OPENAI_API_KEY"))

    def list_models(self) -> List[str]:
        """List all supported OpenAI models with their context limits."""
        return list(OPENAI_MODEL_LIMITS.keys())


class AnthropicProvider(LLMProvider):
    """Anthropic API provider supporting Claude models."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client: Optional[Any] = None

    def _get_client(self) -> Any:
        """Lazily initialize Anthropic client."""
        if self._client is None:
            try:
                from anthropic import Anthropic

                kwargs: Dict[str, Any] = {}
                if self.config.api_key:
                    kwargs["api_key"] = self.config.api_key
                if self.config.api_base:
                    kwargs["base_url"] = self.config.api_base
                kwargs["timeout"] = self.config.timeout
                kwargs["max_retries"] = self.config.max_retries

                self._client = Anthropic(**kwargs)
            except ImportError as exc:
                raise LLMProviderError(
                    "Anthropic SDK not installed. Run: pip install anthropic",
                    provider=ProviderType.ANTHROPIC,
                ) from exc
        return self._client

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate response using Anthropic API."""
        start_time = time.perf_counter()
        client = self._get_client()

        model = request.model or self.config.model
        max_tokens = request.max_tokens or self.config.max_tokens

        # Extract system message if present
        system_content = ""
        messages = []
        for msg in request.messages:
            if msg.role == "system":
                system_content = msg.content
            else:
                messages.append({"role": msg.role, "content": msg.content})

        try:
            kwargs: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if system_content:
                kwargs["system"] = system_content
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            elif self.config.temperature:
                kwargs["temperature"] = self.config.temperature
            if request.stop:
                kwargs["stop_sequences"] = request.stop

            response = client.messages.create(**kwargs)

            latency_ms = (time.perf_counter() - start_time) * 1000

            content = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content += block.text

            return LLMResponse(
                content=content,
                model=response.model,
                provider=ProviderType.ANTHROPIC,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
                latency_ms=latency_ms,
                finish_reason=response.stop_reason,
                raw_response=response.model_dump() if hasattr(response, "model_dump") else None,
            )
        except Exception as exc:
            exc_str = str(exc).lower()
            if "rate_limit" in exc_str or "429" in exc_str:
                raise LLMRateLimitError(str(exc), provider=ProviderType.ANTHROPIC, raw_error=exc)
            if "authentication" in exc_str or "401" in exc_str:
                raise LLMAuthenticationError(str(exc), provider=ProviderType.ANTHROPIC, raw_error=exc)
            raise LLMProviderError(str(exc), provider=ProviderType.ANTHROPIC, raw_error=exc)

    def is_available(self) -> bool:
        """Check if Anthropic is configured."""
        return bool(self.config.api_key or os.environ.get("ANTHROPIC_API_KEY"))


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter API provider - unified access to multiple models.

    OpenRouter provides access to models from OpenAI, Anthropic, Meta, Google,
    and many others through a single API endpoint.
    """

    def __init__(self, config: LLMConfig):
        # Ensure OpenRouter base URL
        if not config.api_base:
            config.api_base = "https://openrouter.ai/api/v1"
        super().__init__(config)

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENROUTER

    def is_available(self) -> bool:
        """Check if OpenRouter is configured."""
        return bool(self.config.api_key or os.environ.get("OPENROUTER_API_KEY"))


class OllamaProvider(LLMProvider):
    """Ollama provider for local model inference."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        if not config.api_base:
            config.api_base = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate response using Ollama API."""
        import urllib.request
        import urllib.error

        start_time = time.perf_counter()
        model = request.model or self.config.model

        # Convert messages to Ollama format
        messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": request.max_tokens or self.config.max_tokens,
                "temperature": request.temperature if request.temperature is not None else self.config.temperature,
            },
        }

        url = f"{self.config.api_base}/api/chat"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            latency_ms = (time.perf_counter() - start_time) * 1000
            message = data.get("message", {})
            content = message.get("content", "")

            # Ollama doesn't provide token counts directly in all versions
            eval_count = data.get("eval_count", 0)
            prompt_eval_count = data.get("prompt_eval_count", 0)

            return LLMResponse(
                content=content,
                model=model,
                provider=ProviderType.OLLAMA,
                input_tokens=prompt_eval_count,
                output_tokens=eval_count,
                total_tokens=prompt_eval_count + eval_count,
                latency_ms=latency_ms,
                finish_reason=data.get("done_reason"),
                raw_response=data,
            )
        except urllib.error.HTTPError as exc:
            raise LLMProviderError(
                f"Ollama request failed: {exc.code} {exc.reason}",
                provider=ProviderType.OLLAMA,
                status_code=exc.code,
                raw_error=exc,
            )
        except urllib.error.URLError as exc:
            raise LLMProviderError(
                f"Cannot connect to Ollama at {self.config.api_base}: {exc.reason}",
                provider=ProviderType.OLLAMA,
                raw_error=exc,
            )

    def is_available(self) -> bool:
        """Check if Ollama is running."""
        import urllib.request
        import urllib.error

        try:
            url = f"{self.config.api_base}/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False


class TogetherProvider(OpenAIProvider):
    """Together AI provider - optimized inference for open-source models."""

    def __init__(self, config: LLMConfig):
        if not config.api_base:
            config.api_base = "https://api.together.xyz/v1"
        super().__init__(config)

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.TOGETHER

    def is_available(self) -> bool:
        return bool(self.config.api_key or os.environ.get("TOGETHER_API_KEY"))


class GroqProvider(OpenAIProvider):
    """Groq provider - ultra-fast inference on LPU hardware."""

    def __init__(self, config: LLMConfig):
        if not config.api_base:
            config.api_base = "https://api.groq.com/openai/v1"
        super().__init__(config)

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.GROQ

    def is_available(self) -> bool:
        return bool(self.config.api_key or os.environ.get("GROQ_API_KEY"))


class FireworksProvider(OpenAIProvider):
    """Fireworks AI provider - optimized open-source model inference."""

    def __init__(self, config: LLMConfig):
        if not config.api_base:
            config.api_base = "https://api.fireworks.ai/inference/v1"
        super().__init__(config)

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.FIREWORKS

    def is_available(self) -> bool:
        return bool(self.config.api_key or os.environ.get("FIREWORKS_API_KEY"))


class TestProvider(LLMProvider):
    """Test provider that returns synthetic responses without calling any LLM API.

    Useful for testing, CI/CD, and development without API keys or running services.
    """

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate synthetic test response."""
        start_time = time.perf_counter()
        model = request.model or self.config.model

        # Build synthetic response that echoes the user query
        user_messages = [msg.content for msg in request.messages if msg.role == "user"]
        user_query = user_messages[-1] if user_messages else "test query"

        synthetic_content = f"""[TEST MODE RESPONSE]

Query: {user_query}

This is a synthetic response from the TestProvider. In production, this would be replaced with actual LLM output.

The request included {len(request.messages)} message(s) and was processed successfully.
"""

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Synthetic token counts
        input_tokens = sum(len(msg.content.split()) * 1.3 for msg in request.messages)
        output_tokens = len(synthetic_content.split()) * 1.3

        return LLMResponse(
            content=synthetic_content,
            model=model,
            provider=ProviderType.TEST,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            total_tokens=int(input_tokens + output_tokens),
            latency_ms=latency_ms,
            finish_reason="test_complete",
            metadata={"test_mode": True},
        )

    def is_available(self) -> bool:
        """Test provider is always available."""
        return True


# Provider registry
_PROVIDER_REGISTRY: Dict[ProviderType, Type[LLMProvider]] = {
    ProviderType.OPENAI: OpenAIProvider,
    ProviderType.ANTHROPIC: AnthropicProvider,
    ProviderType.OPENROUTER: OpenRouterProvider,
    ProviderType.OLLAMA: OllamaProvider,
    ProviderType.TOGETHER: TogetherProvider,
    ProviderType.GROQ: GroqProvider,
    ProviderType.FIREWORKS: FireworksProvider,
    ProviderType.TEST: TestProvider,
}


def get_provider(config: Optional[LLMConfig] = None) -> LLMProvider:
    """Get an LLM provider instance based on configuration.

    Args:
        config: Optional LLMConfig. If not provided, loads from environment.

    Returns:
        Configured LLM provider instance.

    Raises:
        LLMProviderError: If provider type is not supported.
    """
    if config is None:
        config = LLMConfig.from_env()

    provider_class = _PROVIDER_REGISTRY.get(config.provider)
    if provider_class is None:
        raise LLMProviderError(
            f"Unsupported provider: {config.provider}. "
            f"Supported: {', '.join(p.value for p in _PROVIDER_REGISTRY.keys())}",
            provider=config.provider,
        )

    return provider_class(config)


def list_available_providers() -> List[ProviderType]:
    """List all providers that are currently configured and available."""
    available = []
    for provider_type in _PROVIDER_REGISTRY:
        try:
            config = LLMConfig.from_env(provider_type)
            provider = _PROVIDER_REGISTRY[provider_type](config)
            if provider.is_available():
                available.append(provider_type)
        except Exception:
            continue
    return available


class ProviderWithFallback:
    """Wrapper that provides automatic fallback to alternative providers.

    Usage:
        provider = ProviderWithFallback(
            primary=LLMConfig(provider=ProviderType.OPENAI),
            fallbacks=[ProviderType.TEST],
        )
        response = provider.generate(request)
    """

    def __init__(
        self,
        primary: LLMConfig,
        fallbacks: Optional[List[ProviderType]] = None,
        fallback_on_rate_limit: bool = True,
        fallback_on_error: bool = True,
        fallback_on_budget_exceeded: bool = False,
    ):
        """Initialize provider with fallback chain.

        Args:
            primary: Primary provider configuration.
            fallbacks: List of fallback provider types. Default: [TEST] if enabled.
            fallback_on_rate_limit: Whether to fallback on rate limits.
            fallback_on_error: Whether to fallback on general errors.
            fallback_on_budget_exceeded: Whether to fallback on budget exceeded errors.
        """
        self.primary_config = primary
        self.fallbacks = fallbacks or []
        self.fallback_on_rate_limit = fallback_on_rate_limit
        self.fallback_on_error = fallback_on_error
        self.fallback_on_budget_exceeded = fallback_on_budget_exceeded

        self._primary_provider = get_provider(primary)
        self._fallback_providers: List[LLMProvider] = []

        for fallback_type in self.fallbacks:
            try:
                fallback_config = LLMConfig.from_env(fallback_type)
                fallback_provider = get_provider(fallback_config)
                if fallback_provider.is_available():
                    self._fallback_providers.append(fallback_provider)
            except Exception as exc:
                logger.warning(f"Failed to initialize fallback provider {fallback_type}: {exc}")

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate response with automatic fallback on failure.

        Returns:
            LLMResponse from primary or fallback provider.

        Raises:
            LLMProviderError: If all providers fail.
        """
        # Try primary provider
        try:
            response = self._primary_provider.generate(request)
            response.metadata["fallback_used"] = False
            return response
        except LLMRateLimitError as exc:
            if not self.fallback_on_rate_limit:
                raise
            logger.warning(f"Primary provider rate limited, trying fallbacks: {exc}")
            last_error = exc
        except TokenBudgetExceededError as exc:
            if not self.fallback_on_budget_exceeded:
                raise
            logger.warning(f"Primary provider budget exceeded, trying fallbacks: {exc}")
            last_error = exc
        except LLMAuthenticationError:
            # Never fallback on auth errors - configuration issue
            raise
        except LLMProviderError as exc:
            if not self.fallback_on_error:
                raise
            logger.warning(f"Primary provider failed, trying fallbacks: {exc}")
            last_error = exc

        # Try fallback providers
        for i, fallback in enumerate(self._fallback_providers):
            try:
                logger.info(f"Attempting fallback provider {i + 1}/{len(self._fallback_providers)}: "
                           f"{fallback.provider_type.value}")
                response = fallback.generate(request)
                response.metadata["fallback_used"] = True
                response.metadata["fallback_provider"] = fallback.provider_type.value
                response.metadata["fallback_reason"] = str(last_error)
                return response
            except Exception as exc:
                logger.warning(f"Fallback provider {fallback.provider_type.value} failed: {exc}")
                last_error = exc

        # All providers failed
        raise LLMProviderError(
            f"All providers failed. Last error: {last_error}",
            provider=self.primary_config.provider,
            raw_error=last_error,
        )

    def is_available(self) -> bool:
        """Check if at least one provider is available."""
        if self._primary_provider.is_available():
            return True
        return any(p.is_available() for p in self._fallback_providers)


def get_provider_with_fallback(
    config: Optional[LLMConfig] = None,
    fallback_to_test: bool = False,
) -> ProviderWithFallback:
    """Get a provider with automatic TestProvider fallback for local development.

    Args:
        config: Primary provider configuration. If not provided, loads from environment.
        fallback_to_test: Whether to fall back to TestProvider on errors.

    Returns:
        ProviderWithFallback instance.
    """
    if config is None:
        config = LLMConfig.from_env()

    fallbacks = []
    if fallback_to_test and config.provider != ProviderType.TEST:
        fallbacks.append(ProviderType.TEST)

    return ProviderWithFallback(
        primary=config,
        fallbacks=fallbacks,
        fallback_on_rate_limit=True,
        fallback_on_error=fallback_to_test,
        fallback_on_budget_exceeded=False,  # Budget issues should be fixed, not bypassed
    )


__all__ = [
    "ProviderType",
    "LLMConfig",
    "LLMMessage",
    "LLMRequest",
    "LLMResponse",
    "LLMProvider",
    "LLMProviderError",
    "LLMRateLimitError",
    "LLMAuthenticationError",
    "TokenBudgetExceededError",
    "OpenAIProvider",
    "AnthropicProvider",
    "OpenRouterProvider",
    "OllamaProvider",
    "TogetherProvider",
    "GroqProvider",
    "FireworksProvider",
    "TestProvider",
    "get_provider",
    "list_available_providers",
    "ProviderWithFallback",
    "get_provider_with_fallback",
    "calculate_cost",
    "OPENAI_MODEL_LIMITS",
]
