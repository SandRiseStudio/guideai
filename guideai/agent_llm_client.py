"""Agent LLM Client - LLM abstraction for agent execution.

Composes prompts from playbook + work item context + phase + tools schema.
Handles multi-provider support (OpenAI, Anthropic, etc.) with consistent interface.

See WORK_ITEM_EXECUTION_PLAN.md for full specification.
"""

from __future__ import annotations

import json
import math
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Type, Union

from .telemetry import TelemetryClient
from .work_item_execution_contracts import (
    AgentResponse,
    ClarificationQuestion,
    LLMProvider,
    MODEL_CATALOG,
    ModelDefinition,
    ToolCall,
    get_model,
)


logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _short_id(prefix: str) -> str:
    """Generate a short prefixed ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class LLMCallMetrics:
    """Metrics from an LLM call."""
    model_id: str
    provider: LLMProvider
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float
    cached_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "provider": self.provider.value,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "cached_tokens": self.cached_tokens,
        }


class ProviderAdapter(ABC):
    """Abstract base class for LLM provider adapters."""

    @abstractmethod
    async def call(
        self,
        model_id: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[str]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> AgentResponse:
        """Make a call to the LLM provider.

        Args:
            model_id: The model to use
            messages: List of message dicts (role, content)
            tools: Optional list of tool names to enable
            temperature: Sampling temperature
            max_tokens: Maximum output tokens

        Returns:
            AgentResponse with content, tool calls, etc.
        """
        pass

    @abstractmethod
    def get_metrics(self) -> LLMCallMetrics:
        """Get metrics from the last call."""
        pass


class AnthropicAdapter(ProviderAdapter):
    """Adapter for Anthropic Claude models."""

    def __init__(
        self,
        api_key: str,
        tool_registry: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._api_key = api_key
        self._tool_registry = tool_registry or {}
        self._last_metrics: Optional[LLMCallMetrics] = None

        # Lazy import anthropic
        try:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=api_key)
        except ImportError:
            logger.warning("anthropic package not installed, using mock client")
            self._client = None

    async def call(
        self,
        model_id: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[str]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> AgentResponse:
        if not self._client:
            return self._mock_response(messages, tools)

        import time
        start_time = time.time()

        model = get_model(model_id)
        if not model:
            raise ValueError(f"Unknown model: {model_id}")

        # Convert messages to Anthropic format
        anthropic_messages = self._convert_messages(messages)

        # Build tools schema
        tool_schemas = self._build_tool_schemas(tools) if tools else []

        # Call Anthropic
        try:
            response = await self._client.messages.create(
                model=model.api_name,
                max_tokens=max_tokens or model.output_limit,
                temperature=temperature,
                messages=anthropic_messages,
                tools=tool_schemas if tool_schemas else None,
            )

            latency_ms = int((time.time() - start_time) * 1000)

            # Parse response
            result = self._parse_response(response, model_id, latency_ms)

            return result

        except Exception as e:
            logger.exception(f"Anthropic API error: {e}")
            return AgentResponse(
                text_output=f"Error calling Anthropic API: {e}",
                tool_calls=[],
                phase_complete=True,
                needs_clarification=False,
            )

    def get_metrics(self) -> LLMCallMetrics:
        if not self._last_metrics:
            return LLMCallMetrics(
                model_id="unknown",
                provider=LLMProvider.ANTHROPIC,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                cost_usd=0.0,
            )
        return self._last_metrics

    def _convert_messages(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Convert messages to Anthropic format."""
        anthropic_messages = []
        system_content = None

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_content = content
            elif role == "tool":
                # Convert tool result to Anthropic format
                anthropic_messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "content": content}],
                })
            else:
                anthropic_messages.append({
                    "role": role,
                    "content": content,
                })

        # Prepend system message if present
        if system_content and anthropic_messages:
            first_msg = anthropic_messages[0]
            if first_msg["role"] == "user":
                first_msg["content"] = f"{system_content}\n\n{first_msg['content']}"

        return anthropic_messages

    def _build_tool_schemas(self, tools: List[str]) -> List[Dict[str, Any]]:
        """Build tool schemas for Anthropic."""
        schemas = []

        for tool_name in tools:
            if tool_name in self._tool_registry:
                schema = self._tool_registry[tool_name]
                schemas.append({
                    "name": tool_name,
                    "description": schema.get("description", ""),
                    "input_schema": schema.get("input_schema", {"type": "object"}),
                })
            else:
                # Default schema
                schemas.append({
                    "name": tool_name,
                    "description": f"Execute {tool_name} tool",
                    "input_schema": {"type": "object", "properties": {}},
                })

        return schemas

    def _parse_response(
        self,
        response: Any,
        model_id: str,
        latency_ms: int,
    ) -> AgentResponse:
        """Parse Anthropic response into AgentResponse."""
        content = ""
        tool_calls: List[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    call_id=block.id,
                    tool_name=block.name,
                    tool_args=block.input,  # Fixed: was 'inputs', should be 'tool_args'
                ))

        # Calculate cost
        model = get_model(model_id)
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        cost_usd = 0.0
        if model:
            # Use input_price_per_m and output_price_per_m directly from ModelDefinition
            cost_usd = (
                (input_tokens / 1_000_000) * model.input_price_per_m +
                (output_tokens / 1_000_000) * model.output_price_per_m
            )

        self._last_metrics = LLMCallMetrics(
            model_id=model_id,
            provider=LLMProvider.ANTHROPIC,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            cached_tokens=getattr(response.usage, "cache_read_input_tokens", 0),
        )

        # Check if response indicates completion or clarification needed
        phase_complete = response.stop_reason == "end_turn" and not tool_calls

        # Only trigger clarification if the LLM is explicitly asking for user input
        # Look for explicit clarification requests, not just mentions of "question"
        content_lower = content.lower()
        needs_clarification = (
            # Explicit clarification patterns
            "need clarification" in content_lower or
            "please clarify" in content_lower or
            "could you clarify" in content_lower or
            "can you clarify" in content_lower or
            "require clarification" in content_lower or
            "before i proceed" in content_lower or
            "before proceeding" in content_lower or
            # Explicit question patterns directed at user
            "could you please" in content_lower or
            "can you please" in content_lower or
            "i need to know" in content_lower or
            "please let me know" in content_lower or
            "please provide" in content_lower
        )

        clarification_questions: List[ClarificationQuestion] = []
        if needs_clarification:
            clarification_questions.append(ClarificationQuestion(
                question_id=_short_id("clar"),
                question=content,
                context="Extracted from LLM response",
            ))

        return AgentResponse(
            text_output=content,
            tool_calls=tool_calls,
            clarification_questions=clarification_questions,
            needs_clarification=needs_clarification,
            phase_complete=phase_complete,
            model_id=model_id,
            input_tokens=self._last_metrics.input_tokens,
            output_tokens=self._last_metrics.output_tokens,
            cost_usd=self._last_metrics.cost_usd,
        )

    def _mock_response(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[str]],
    ) -> AgentResponse:
        """Return a mock response when client is not available."""
        return AgentResponse(
            text_output="Mock response - Anthropic client not available",
            tool_calls=[],
            phase_complete=True,
            needs_clarification=False,
        )


class OpenAIAdapter(ProviderAdapter):
    """Adapter for OpenAI GPT models."""

    def __init__(
        self,
        api_key: str,
        tool_registry: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._api_key = api_key
        self._tool_registry = tool_registry or {}
        self._last_metrics: Optional[LLMCallMetrics] = None

        # Lazy import openai
        try:
            import openai
            self._client = openai.AsyncOpenAI(api_key=api_key)
        except ImportError:
            logger.warning("openai package not installed, using mock client")
            self._client = None

    async def call(
        self,
        model_id: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[str]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> AgentResponse:
        if not self._client:
            return self._mock_response(messages, tools)

        import time
        start_time = time.time()

        model = get_model(model_id)
        if not model:
            raise ValueError(f"Unknown model: {model_id}")

        # Build tools schema
        tool_schemas = self._build_tool_schemas(tools) if tools else None

        # Call OpenAI
        try:
            response = await self._client.chat.completions.create(
                model=model.api_name,
                max_tokens=max_tokens or model.output_limit,
                temperature=temperature,
                messages=messages,
                tools=tool_schemas,
            )

            latency_ms = int((time.time() - start_time) * 1000)

            # Parse response
            result = self._parse_response(response, model_id, latency_ms)

            return result

        except Exception as e:
            logger.exception(f"OpenAI API error: {e}")
            return AgentResponse(
                text_output=f"Error calling OpenAI API: {e}",
                tool_calls=[],
                phase_complete=True,
                needs_clarification=False,
            )

    def get_metrics(self) -> LLMCallMetrics:
        if not self._last_metrics:
            return LLMCallMetrics(
                model_id="unknown",
                provider=LLMProvider.OPENAI,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                cost_usd=0.0,
            )
        return self._last_metrics

    def _build_tool_schemas(self, tools: List[str]) -> List[Dict[str, Any]]:
        """Build tool schemas for OpenAI."""
        schemas = []

        for tool_name in tools:
            if tool_name in self._tool_registry:
                schema = self._tool_registry[tool_name]
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": schema.get("description", ""),
                        "parameters": schema.get("input_schema", {"type": "object"}),
                    },
                })
            else:
                # Default schema
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": f"Execute {tool_name} tool",
                        "parameters": {"type": "object", "properties": {}},
                    },
                })

        return schemas

    def _parse_response(
        self,
        response: Any,
        model_id: str,
        latency_ms: int,
    ) -> AgentResponse:
        """Parse OpenAI response into AgentResponse."""
        choice = response.choices[0]
        message = choice.message

        content = message.content or ""
        tool_calls: List[ToolCall] = []

        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(ToolCall(
                    call_id=tc.id,
                    tool_name=tc.function.name,
                    tool_args=json.loads(tc.function.arguments) if tc.function.arguments else {},  # Fixed: was 'inputs'
                ))

        # Calculate cost
        model = get_model(model_id)
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens

        cost_usd = 0.0
        if model:
            # Use input_price_per_m and output_price_per_m directly from ModelDefinition
            cost_usd = (
                (input_tokens / 1_000_000) * model.input_price_per_m +
                (output_tokens / 1_000_000) * model.output_price_per_m
            )

        self._last_metrics = LLMCallMetrics(
            model_id=model_id,
            provider=LLMProvider.OPENAI,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )

        # Check if response indicates completion or clarification needed
        phase_complete = choice.finish_reason == "stop" and not tool_calls

        # Only trigger clarification if the LLM is explicitly asking for user input
        # Look for explicit clarification requests, not just mentions of "question"
        content_lower = content.lower()
        needs_clarification = (
            # Explicit clarification patterns
            "need clarification" in content_lower or
            "please clarify" in content_lower or
            "could you clarify" in content_lower or
            "can you clarify" in content_lower or
            "require clarification" in content_lower or
            "before i proceed" in content_lower or
            "before proceeding" in content_lower or
            # Explicit question patterns directed at user
            "could you please" in content_lower or
            "can you please" in content_lower or
            "i need to know" in content_lower or
            "please let me know" in content_lower or
            "please provide" in content_lower
        )

        clarification_questions: List[ClarificationQuestion] = []
        if needs_clarification:
            clarification_questions.append(ClarificationQuestion(
                question_id=_short_id("clar"),
                question=content,
                context="Extracted from LLM response",
            ))

        return AgentResponse(
            text_output=content,
            tool_calls=tool_calls,
            clarification_questions=clarification_questions,
            needs_clarification=needs_clarification,
            phase_complete=phase_complete,
            model_id=model_id,
            input_tokens=self._last_metrics.input_tokens,
            output_tokens=self._last_metrics.output_tokens,
            cost_usd=self._last_metrics.cost_usd,
        )

    def _mock_response(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[str]],
    ) -> AgentResponse:
        """Return a mock response when client is not available."""
        return AgentResponse(
            text_output="Mock response - OpenAI client not available",
            tool_calls=[],
            phase_complete=True,
            needs_clarification=False,
        )


class AgentLLMClient:
    """LLM abstraction for agent execution.

    This class provides a unified interface for calling different LLM providers
    while handling:
    - Provider-specific API differences
    - Tool schema formatting
    - Token counting and cost tracking
    - Retry logic and error handling
    """

    # Provider adapter classes
    _ADAPTERS: Dict[LLMProvider, Type[ProviderAdapter]] = {
        LLMProvider.ANTHROPIC: AnthropicAdapter,
        LLMProvider.OPENAI: OpenAIAdapter,
    }

    def __init__(
        self,
        *,
        credential_resolver: Optional[Callable[[str], Optional[str]]] = None,
        tool_registry: Optional[Dict[str, Any]] = None,
        telemetry: Optional[TelemetryClient] = None,
        default_temperature: float = 0.0,
    ) -> None:
        """Initialize AgentLLMClient.

        Args:
            credential_resolver: Function to resolve API key for a provider
            tool_registry: Registry of tool schemas
            telemetry: Telemetry client for metrics
            default_temperature: Default sampling temperature
        """
        self._credential_resolver = credential_resolver or self._default_credential_resolver
        self._tool_registry = tool_registry or {}
        self._telemetry = telemetry or TelemetryClient.noop()
        self._default_temperature = default_temperature

        # Cache of initialized adapters
        self._adapters: Dict[str, ProviderAdapter] = {}

        # Call history for tracking
        self._call_history: List[LLMCallMetrics] = []

    def _default_credential_resolver(self, provider: str) -> Optional[str]:
        """Default credential resolver using environment variables."""
        import os

        env_vars = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }

        env_var = env_vars.get(provider)
        if env_var:
            return os.getenv(env_var)

        return None

    @staticmethod
    def _estimate_tokens_from_text(text: str) -> int:
        """Estimate token count from text length.

        Uses a conservative heuristic of ~4 characters per token.
        """
        if not text:
            return 0
        return max(1, math.ceil(len(text) / 4))

    @staticmethod
    def _estimate_tokens_from_messages(messages: List[Dict[str, Any]]) -> int:
        """Estimate input tokens from message contents."""
        if not messages:
            return 0

        total_chars = 0
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        text = block.get("text")
                        if isinstance(text, str):
                            total_chars += len(text)
            elif content is not None:
                total_chars += len(str(content))

        return max(1, math.ceil(total_chars / 4))

    def _get_adapter(
        self,
        model_id: str,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> ProviderAdapter:
        """Get or create adapter for a model's provider.

        Args:
            model_id: The model to get adapter for
            project_id: Optional project context for BYOK resolution
            org_id: Optional org context for BYOK resolution
        """
        model = get_model(model_id)
        if not model:
            raise ValueError(f"Unknown model: {model_id}")

        provider = model.provider

        # Build cache key with context for BYOK credentials
        cache_key = f"{model_id}:{project_id or ''}:{org_id or ''}"

        # Check cache
        if cache_key in self._adapters:
            return self._adapters[cache_key]

        # Get API key - try context-aware resolver first
        api_key = None
        if hasattr(self._credential_resolver, '__code__') and self._credential_resolver.__code__.co_argcount >= 3:
            # Context-aware resolver (provider, project_id, org_id) -> key
            api_key = self._credential_resolver(provider.value, project_id, org_id)
        else:
            # Simple resolver (provider) -> key
            api_key = self._credential_resolver(provider.value)

        if not api_key:
            raise ValueError(f"No API key available for provider: {provider.value}")

        # Create adapter
        adapter_class = self._ADAPTERS.get(provider)
        if not adapter_class:
            raise ValueError(f"No adapter for provider: {provider.value}")

        adapter = adapter_class(api_key=api_key, tool_registry=self._tool_registry)
        self._adapters[cache_key] = adapter

        return adapter

    async def call(
        self,
        model_id: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> AgentResponse:
        """Make an LLM call.

        Args:
            model_id: The model to use (from MODEL_CATALOG)
            messages: List of message dicts (role, content)
            tools: Optional list of tool names to enable
            temperature: Sampling temperature (0.0 - 1.0)
            max_tokens: Maximum output tokens
            project_id: Optional project context for BYOK credential resolution
            org_id: Optional org context for BYOK credential resolution

        Returns:
            AgentResponse with content, tool calls, metrics
        """
        # Get adapter
        adapter = self._get_adapter(model_id, project_id, org_id)

        # Make call
        response = await adapter.call(
            model_id=model_id,
            messages=messages,
            tools=tools,
            temperature=temperature or self._default_temperature,
            max_tokens=max_tokens,
        )

        # Track metrics
        metrics = adapter.get_metrics()
        self._call_history.append(metrics)

        # Backfill token counts if provider did not return usage
        if response.input_tokens == 0 and metrics.input_tokens:
            response.input_tokens = metrics.input_tokens
        if response.output_tokens == 0 and metrics.output_tokens:
            response.output_tokens = metrics.output_tokens

        if response.input_tokens == 0 and response.output_tokens == 0:
            response.input_tokens = self._estimate_tokens_from_messages(messages)
            response.output_tokens = self._estimate_tokens_from_text(response.text_output)

        # Emit telemetry
        self._telemetry.emit_event(
            event_type="llm.call.completed",
            payload={
                "model_id": model_id,
                "input_tokens": metrics.input_tokens,
                "output_tokens": metrics.output_tokens,
                "latency_ms": metrics.latency_ms,
                "cost_usd": metrics.cost_usd,
                "tool_calls": len(response.tool_calls),
            },
        )

        return response

    def get_total_cost(self) -> float:
        """Get total cost of all calls in this session."""
        return sum(m.cost_usd for m in self._call_history)

    def get_total_tokens(self) -> Dict[str, int]:
        """Get total tokens used in this session."""
        return {
            "input": sum(m.input_tokens for m in self._call_history),
            "output": sum(m.output_tokens for m in self._call_history),
            "total": sum(m.input_tokens + m.output_tokens for m in self._call_history),
        }

    def get_call_history(self) -> List[LLMCallMetrics]:
        """Get history of all calls in this session."""
        return list(self._call_history)

    def register_tool(self, name: str, schema: Dict[str, Any]) -> None:
        """Register a tool schema."""
        self._tool_registry[name] = schema

    def register_tools(self, tools: Dict[str, Any]) -> None:
        """Register multiple tool schemas."""
        self._tool_registry.update(tools)


# Convenience function for creating a client
def create_llm_client(
    *,
    tool_registry: Optional[Dict[str, Any]] = None,
    telemetry: Optional[TelemetryClient] = None,
) -> AgentLLMClient:
    """Create an AgentLLMClient with default configuration."""
    return AgentLLMClient(
        tool_registry=tool_registry,
        telemetry=telemetry,
    )
