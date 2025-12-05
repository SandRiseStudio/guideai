"""Evaluation service for fine-tuned models.

Provides automated evaluation pipelines for:
- Behavior adherence scoring
- Hallucination detection
- A/B model comparison
- Benchmark dataset management

Example:
    from mdnt import MidnighterService
    from mdnt.evaluation import EvaluationService

    eval_service = EvaluationService(midnighter=midnighter_service)

    # Run evaluation on a fine-tuned model
    result = await eval_service.evaluate_model(
        model_id="my-finetuned-model",
        benchmark="behavior_adherence",
    )

    # Compare two models
    comparison = await eval_service.compare_models(
        baseline_model="gpt-4o-mini",
        candidate_model="ft:gpt-4o-mini:my-org:my-model:abc123",
        test_behaviors=["behavior_code_review", "behavior_logging"],
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

logger = logging.getLogger(__name__)

# Check for OpenAI availability
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    AsyncOpenAI = None  # type: ignore
    OPENAI_AVAILABLE = False


class EvaluationMetric(str, Enum):
    """Evaluation metrics for fine-tuned models."""
    BEHAVIOR_ADHERENCE = "behavior_adherence"
    CITATION_ACCURACY = "citation_accuracy"
    HALLUCINATION_RATE = "hallucination_rate"
    RESPONSE_QUALITY = "response_quality"
    LATENCY_P50 = "latency_p50"
    LATENCY_P99 = "latency_p99"
    TOKEN_EFFICIENCY = "token_efficiency"


@dataclass
class BenchmarkExample:
    """Single example in an evaluation benchmark."""
    example_id: str
    prompt: str
    expected_behaviors: List[str]
    context: Optional[str] = None
    expected_response_contains: Optional[List[str]] = None
    expected_response_excludes: Optional[List[str]] = None
    difficulty: str = "medium"  # easy, medium, hard
    category: str = "general"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "example_id": self.example_id,
            "prompt": self.prompt,
            "expected_behaviors": self.expected_behaviors,
            "context": self.context,
            "expected_response_contains": self.expected_response_contains,
            "expected_response_excludes": self.expected_response_excludes,
            "difficulty": self.difficulty,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkExample":
        return cls(
            example_id=data.get("example_id", str(uuid.uuid4())),
            prompt=data["prompt"],
            expected_behaviors=data["expected_behaviors"],
            context=data.get("context"),
            expected_response_contains=data.get("expected_response_contains"),
            expected_response_excludes=data.get("expected_response_excludes"),
            difficulty=data.get("difficulty", "medium"),
            category=data.get("category", "general"),
        )


@dataclass
class EvaluationResult:
    """Result of evaluating a model on a benchmark."""
    evaluation_id: str
    model_id: str
    benchmark_name: str
    started_at: datetime
    completed_at: Optional[datetime]
    total_examples: int
    completed_examples: int
    metrics: Dict[str, float]
    example_results: List[Dict[str, Any]]
    errors: List[str]
    status: str = "running"  # running, completed, failed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "model_id": self.model_id,
            "benchmark_name": self.benchmark_name,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_examples": self.total_examples,
            "completed_examples": self.completed_examples,
            "metrics": self.metrics,
            "example_results": self.example_results,
            "errors": self.errors,
            "status": self.status,
        }


@dataclass
class ComparisonResult:
    """Result of comparing two models."""
    comparison_id: str
    baseline_model: str
    candidate_model: str
    benchmark_name: str
    started_at: datetime
    completed_at: Optional[datetime]
    total_examples: int
    baseline_metrics: Dict[str, float]
    candidate_metrics: Dict[str, float]
    improvement: Dict[str, float]  # Positive = candidate better
    winner: str  # "baseline", "candidate", or "tie"
    confidence: float  # 0-1
    example_comparisons: List[Dict[str, Any]]
    status: str = "running"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "baseline_model": self.baseline_model,
            "candidate_model": self.candidate_model,
            "benchmark_name": self.benchmark_name,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_examples": self.total_examples,
            "baseline_metrics": self.baseline_metrics,
            "candidate_metrics": self.candidate_metrics,
            "improvement": self.improvement,
            "winner": self.winner,
            "confidence": self.confidence,
            "example_comparisons": self.example_comparisons,
            "status": self.status,
        }


@dataclass
class Benchmark:
    """Evaluation benchmark with test examples."""
    name: str
    description: str
    examples: List[BenchmarkExample]
    version: str = "1.0"
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "examples": [ex.to_dict() for ex in self.examples],
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Benchmark":
        examples = [BenchmarkExample.from_dict(ex) for ex in data.get("examples", [])]
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            examples=examples,
            version=data.get("version", "1.0"),
            created_at=created_at,
        )

    def save(self, path: str) -> None:
        """Save benchmark to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "Benchmark":
        """Load benchmark from JSON file."""
        with open(path) as f:
            return cls.from_dict(json.load(f))


class EvaluationService:
    """Service for evaluating fine-tuned models.

    Provides:
    - Behavior adherence evaluation
    - Hallucination detection
    - A/B model comparison
    - Benchmark management
    - Cost tracking for evaluations

    Example:
        eval_service = EvaluationService()

        # Evaluate a model
        result = await eval_service.evaluate_model(
            model_id="ft:gpt-4o-mini:my-org:mdnt-model:abc123",
            benchmark="behavior_adherence",
        )

        print(f"Behavior Adherence: {result.metrics['behavior_adherence']:.2%}")
        print(f"Hallucination Rate: {result.metrics['hallucination_rate']:.2%}")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        on_metric: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_cost: Optional[Callable[[str, int, float], None]] = None,
        benchmarks_dir: str = "./benchmarks",
    ) -> None:
        """Initialize evaluation service.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var).
            on_metric: Callback for metrics (event_type, data).
            on_cost: Callback for cost tracking (job_id, tokens, cost_usd).
            benchmarks_dir: Directory for benchmark files.
        """
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._on_metric = on_metric
        self._on_cost = on_cost
        self._benchmarks_dir = benchmarks_dir

        # Cached benchmarks
        self._benchmarks: Dict[str, Benchmark] = {}

        # Pricing (as of 2024)
        self._pricing = {
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},  # per 1M tokens
            "gpt-4o": {"input": 2.50, "output": 10.00},
            "ft:gpt-4o-mini": {"input": 0.30, "output": 1.20},  # Fine-tuned
            "ft:gpt-4o": {"input": 5.00, "output": 20.00},
        }

        # Create benchmarks directory
        os.makedirs(self._benchmarks_dir, exist_ok=True)

        logger.info("EvaluationService initialized (benchmarks_dir=%s)", benchmarks_dir)

    async def evaluate_model(
        self,
        model_id: str,
        benchmark: str | Benchmark,
        *,
        sample_size: Optional[int] = None,
        timeout_per_example: float = 30.0,
        temperature: float = 0.0,
    ) -> EvaluationResult:
        """Evaluate a model on a benchmark.

        Args:
            model_id: Model to evaluate (fine-tuned or base).
            benchmark: Benchmark name or Benchmark object.
            sample_size: Limit examples (None = all).
            timeout_per_example: Timeout per inference.
            temperature: Sampling temperature.

        Returns:
            EvaluationResult with metrics and per-example results.
        """
        if not OPENAI_AVAILABLE:
            raise ImportError("openai package required: pip install midnighter[openai]")

        # Load benchmark
        if isinstance(benchmark, str):
            bench = self.get_benchmark(benchmark)
            if not bench:
                raise ValueError(f"Benchmark not found: {benchmark}")
        else:
            bench = benchmark

        # Select examples
        examples = bench.examples
        if sample_size and sample_size < len(examples):
            import random
            examples = random.sample(examples, sample_size)

        evaluation_id = str(uuid.uuid4())
        result = EvaluationResult(
            evaluation_id=evaluation_id,
            model_id=model_id,
            benchmark_name=bench.name,
            started_at=datetime.utcnow(),
            completed_at=None,
            total_examples=len(examples),
            completed_examples=0,
            metrics={},
            example_results=[],
            errors=[],
            status="running",
        )

        # Initialize OpenAI client
        client = AsyncOpenAI(api_key=self._api_key)

        # Track metrics
        total_tokens = 0
        behavior_adherence_scores: List[float] = []
        citation_accuracy_scores: List[float] = []
        hallucination_scores: List[float] = []
        latencies: List[float] = []

        # Evaluate each example
        for example in examples:
            try:
                start_time = asyncio.get_event_loop().time()

                # Build prompt
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are a helpful AI assistant that follows behavior-conditioned guidelines. "
                            "When applying behaviors, cite them in your response using the format: `behavior_name` (Role)."
                        ),
                    },
                ]
                if example.context:
                    messages.append({"role": "system", "content": f"Context: {example.context}"})
                messages.append({"role": "user", "content": example.prompt})

                # Get response
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model_id,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=1000,
                    ),
                    timeout=timeout_per_example,
                )

                end_time = asyncio.get_event_loop().time()
                latency = end_time - start_time
                latencies.append(latency)

                # Extract response
                response_text = response.choices[0].message.content or ""
                tokens_used = response.usage.total_tokens if response.usage else 0
                total_tokens += tokens_used

                # Score response
                adherence = self._score_behavior_adherence(
                    response_text,
                    example.expected_behaviors,
                )
                behavior_adherence_scores.append(adherence)

                citation = self._score_citation_accuracy(
                    response_text,
                    example.expected_behaviors,
                )
                citation_accuracy_scores.append(citation)

                hallucination = self._detect_hallucinations(
                    response_text,
                    example.expected_behaviors,
                    example.expected_response_excludes,
                )
                hallucination_scores.append(hallucination)

                # Check expected content
                contains_expected = True
                if example.expected_response_contains:
                    for expected in example.expected_response_contains:
                        if expected.lower() not in response_text.lower():
                            contains_expected = False
                            break

                excludes_forbidden = True
                if example.expected_response_excludes:
                    for forbidden in example.expected_response_excludes:
                        if forbidden.lower() in response_text.lower():
                            excludes_forbidden = False
                            break

                result.example_results.append({
                    "example_id": example.example_id,
                    "prompt": example.prompt[:100] + "..." if len(example.prompt) > 100 else example.prompt,
                    "response": response_text[:200] + "..." if len(response_text) > 200 else response_text,
                    "expected_behaviors": example.expected_behaviors,
                    "behavior_adherence": adherence,
                    "citation_accuracy": citation,
                    "hallucination_score": hallucination,
                    "contains_expected": contains_expected,
                    "excludes_forbidden": excludes_forbidden,
                    "latency_seconds": latency,
                    "tokens": tokens_used,
                })

                result.completed_examples += 1

            except asyncio.TimeoutError:
                result.errors.append(f"Timeout on example {example.example_id}")
            except Exception as e:
                result.errors.append(f"Error on example {example.example_id}: {str(e)}")
                logger.exception("Error evaluating example %s", example.example_id)

        # Calculate aggregate metrics
        if behavior_adherence_scores:
            result.metrics[EvaluationMetric.BEHAVIOR_ADHERENCE.value] = (
                sum(behavior_adherence_scores) / len(behavior_adherence_scores)
            )
        if citation_accuracy_scores:
            result.metrics[EvaluationMetric.CITATION_ACCURACY.value] = (
                sum(citation_accuracy_scores) / len(citation_accuracy_scores)
            )
        if hallucination_scores:
            result.metrics[EvaluationMetric.HALLUCINATION_RATE.value] = (
                sum(hallucination_scores) / len(hallucination_scores)
            )
        if latencies:
            sorted_latencies = sorted(latencies)
            result.metrics[EvaluationMetric.LATENCY_P50.value] = (
                sorted_latencies[len(sorted_latencies) // 2]
            )
            result.metrics[EvaluationMetric.LATENCY_P99.value] = (
                sorted_latencies[int(len(sorted_latencies) * 0.99)]
            )

        result.metrics["total_tokens"] = total_tokens
        result.metrics["examples_evaluated"] = result.completed_examples

        # Calculate cost
        cost_usd = self._calculate_cost(model_id, total_tokens)
        result.metrics["cost_usd"] = cost_usd

        # Emit cost callback
        if self._on_cost:
            self._on_cost(evaluation_id, total_tokens, cost_usd)

        # Emit metric callback
        if self._on_metric:
            self._on_metric("evaluation_completed", {
                "evaluation_id": evaluation_id,
                "model_id": model_id,
                "benchmark": bench.name,
                "behavior_adherence": result.metrics.get(EvaluationMetric.BEHAVIOR_ADHERENCE.value, 0),
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
            })

        result.completed_at = datetime.utcnow()
        result.status = "completed" if not result.errors else "completed_with_errors"

        return result

    async def compare_models(
        self,
        baseline_model: str,
        candidate_model: str,
        benchmark: str | Benchmark,
        *,
        sample_size: Optional[int] = None,
    ) -> ComparisonResult:
        """Compare two models on the same benchmark.

        Args:
            baseline_model: Baseline model ID.
            candidate_model: Candidate model ID (usually fine-tuned).
            benchmark: Benchmark name or object.
            sample_size: Limit examples.

        Returns:
            ComparisonResult with improvement metrics.
        """
        comparison_id = str(uuid.uuid4())

        # Run evaluations in parallel
        baseline_result, candidate_result = await asyncio.gather(
            self.evaluate_model(baseline_model, benchmark, sample_size=sample_size),
            self.evaluate_model(candidate_model, benchmark, sample_size=sample_size),
        )

        # Calculate improvements
        improvement: Dict[str, float] = {}
        for metric in [
            EvaluationMetric.BEHAVIOR_ADHERENCE.value,
            EvaluationMetric.CITATION_ACCURACY.value,
        ]:
            baseline_val = baseline_result.metrics.get(metric, 0)
            candidate_val = candidate_result.metrics.get(metric, 0)
            if baseline_val > 0:
                improvement[metric] = (candidate_val - baseline_val) / baseline_val
            else:
                improvement[metric] = candidate_val

        # Hallucination: lower is better
        baseline_hall = baseline_result.metrics.get(EvaluationMetric.HALLUCINATION_RATE.value, 0)
        candidate_hall = candidate_result.metrics.get(EvaluationMetric.HALLUCINATION_RATE.value, 0)
        if baseline_hall > 0:
            improvement[EvaluationMetric.HALLUCINATION_RATE.value] = (baseline_hall - candidate_hall) / baseline_hall
        else:
            improvement[EvaluationMetric.HALLUCINATION_RATE.value] = -candidate_hall

        # Determine winner
        adherence_better = improvement.get(EvaluationMetric.BEHAVIOR_ADHERENCE.value, 0) > 0.05
        hallucination_better = improvement.get(EvaluationMetric.HALLUCINATION_RATE.value, 0) > 0.05

        if adherence_better and hallucination_better:
            winner = "candidate"
            confidence = 0.9
        elif adherence_better or hallucination_better:
            winner = "candidate"
            confidence = 0.7
        elif improvement.get(EvaluationMetric.BEHAVIOR_ADHERENCE.value, 0) < -0.05:
            winner = "baseline"
            confidence = 0.7
        else:
            winner = "tie"
            confidence = 0.5

        # Build example comparisons
        example_comparisons = []
        for base_ex, cand_ex in zip(baseline_result.example_results, candidate_result.example_results):
            example_comparisons.append({
                "example_id": base_ex.get("example_id"),
                "baseline_adherence": base_ex.get("behavior_adherence", 0),
                "candidate_adherence": cand_ex.get("behavior_adherence", 0),
                "baseline_response": base_ex.get("response", "")[:100],
                "candidate_response": cand_ex.get("response", "")[:100],
            })

        return ComparisonResult(
            comparison_id=comparison_id,
            baseline_model=baseline_model,
            candidate_model=candidate_model,
            benchmark_name=baseline_result.benchmark_name,
            started_at=baseline_result.started_at,
            completed_at=datetime.utcnow(),
            total_examples=baseline_result.total_examples,
            baseline_metrics=baseline_result.metrics,
            candidate_metrics=candidate_result.metrics,
            improvement=improvement,
            winner=winner,
            confidence=confidence,
            example_comparisons=example_comparisons,
            status="completed",
        )

    def get_benchmark(self, name: str) -> Optional[Benchmark]:
        """Get a benchmark by name."""
        if name in self._benchmarks:
            return self._benchmarks[name]

        # Try to load from file
        path = os.path.join(self._benchmarks_dir, f"{name}.json")
        if os.path.exists(path):
            bench = Benchmark.load(path)
            self._benchmarks[name] = bench
            return bench

        # Check for built-in benchmarks
        if name == "behavior_adherence":
            return self._create_default_benchmark()

        return None

    def register_benchmark(self, benchmark: Benchmark, save: bool = True) -> None:
        """Register a benchmark."""
        self._benchmarks[benchmark.name] = benchmark
        if save:
            path = os.path.join(self._benchmarks_dir, f"{benchmark.name}.json")
            benchmark.save(path)
            logger.info("Saved benchmark to %s", path)

    def list_benchmarks(self) -> List[str]:
        """List available benchmarks."""
        benchmarks = list(self._benchmarks.keys())

        # Add file-based benchmarks
        if os.path.exists(self._benchmarks_dir):
            for filename in os.listdir(self._benchmarks_dir):
                if filename.endswith(".json"):
                    name = filename[:-5]
                    if name not in benchmarks:
                        benchmarks.append(name)

        # Add built-in
        if "behavior_adherence" not in benchmarks:
            benchmarks.append("behavior_adherence")

        return benchmarks

    def _score_behavior_adherence(
        self,
        response: str,
        expected_behaviors: List[str],
    ) -> float:
        """Score how well the response adheres to expected behaviors.

        Checks for:
        1. Behavior citations (backtick format)
        2. Behavior name mentions
        3. Role annotations (Student/Teacher/Strategist)
        """
        if not expected_behaviors:
            return 1.0

        score = 0.0
        for behavior in expected_behaviors:
            # Full citation: `behavior_name` (Role)
            citation_pattern = rf"`{re.escape(behavior)}`\s*\([^)]+\)"
            if re.search(citation_pattern, response):
                score += 1.0
            # Partial citation: `behavior_name`
            elif f"`{behavior}`" in response:
                score += 0.8
            # Just mentioned
            elif behavior in response:
                score += 0.5
            # Behavior concept mentioned (without exact name)
            elif behavior.replace("behavior_", "").replace("_", " ") in response.lower():
                score += 0.3

        return score / len(expected_behaviors)

    def _score_citation_accuracy(
        self,
        response: str,
        expected_behaviors: List[str],
    ) -> float:
        """Score citation format accuracy."""
        # Find all citations in response
        citations = re.findall(r"`(behavior_[a-z_]+)`", response)

        if not citations:
            return 0.0

        # Check if citations are valid
        valid_citations = [c for c in citations if c in expected_behaviors]
        accuracy = len(valid_citations) / len(citations) if citations else 0.0

        # Bonus for proper role annotation
        role_citations = re.findall(r"`behavior_[a-z_]+`\s*\((Student|Teacher|Metacognitive Strategist)\)", response)
        if role_citations:
            accuracy = min(1.0, accuracy + 0.1)

        return accuracy

    def _detect_hallucinations(
        self,
        response: str,
        expected_behaviors: List[str],
        forbidden_content: Optional[List[str]] = None,
    ) -> float:
        """Detect hallucination rate (0 = no hallucinations, 1 = all hallucinations).

        Checks for:
        1. Made-up behavior names
        2. Forbidden content
        3. Confident but wrong statements
        """
        hallucination_score = 0.0
        checks = 0

        # Check for made-up behaviors
        cited_behaviors = re.findall(r"`(behavior_[a-z_]+)`", response)
        if cited_behaviors:
            fake_behaviors = [b for b in cited_behaviors if b not in expected_behaviors]
            if fake_behaviors:
                hallucination_score += len(fake_behaviors) / len(cited_behaviors)
            checks += 1

        # Check for forbidden content
        if forbidden_content:
            for forbidden in forbidden_content:
                if forbidden.lower() in response.lower():
                    hallucination_score += 1.0
                    checks += 1
            if not any(f.lower() in response.lower() for f in forbidden_content):
                checks += 1  # Passed the check

        return hallucination_score / max(checks, 1)

    def _calculate_cost(self, model_id: str, total_tokens: int) -> float:
        """Calculate cost for token usage."""
        # Determine pricing tier
        if model_id.startswith("ft:gpt-4o-mini"):
            pricing = self._pricing["ft:gpt-4o-mini"]
        elif model_id.startswith("ft:gpt-4o"):
            pricing = self._pricing["ft:gpt-4o"]
        elif "gpt-4o-mini" in model_id:
            pricing = self._pricing["gpt-4o-mini"]
        elif "gpt-4o" in model_id:
            pricing = self._pricing["gpt-4o"]
        else:
            pricing = self._pricing["gpt-4o-mini"]  # Default

        # Approximate 50/50 split between input and output
        input_tokens = total_tokens // 2
        output_tokens = total_tokens - input_tokens

        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
        return round(cost, 4)

    def _create_default_benchmark(self) -> Benchmark:
        """Create default behavior adherence benchmark."""
        examples = [
            BenchmarkExample(
                example_id="ba-001",
                prompt="How should I add logging to my new API endpoint?",
                expected_behaviors=["behavior_use_raze_for_logging"],
                expected_response_contains=["Raze", "RazeLogger"],
                category="logging",
            ),
            BenchmarkExample(
                example_id="ba-002",
                prompt="I need to set up a development environment for our service.",
                expected_behaviors=["behavior_use_amprealize_for_environments"],
                expected_response_contains=["Amprealize", "blueprint"],
                category="environments",
            ),
            BenchmarkExample(
                example_id="ba-003",
                prompt="What's the best way to call external APIs in this project?",
                expected_behaviors=["behavior_prefer_mcp_tools"],
                expected_response_contains=["MCP"],
                category="tooling",
            ),
            BenchmarkExample(
                example_id="ba-004",
                prompt="I found a hardcoded API key in the code. What should I do?",
                expected_behaviors=["behavior_prevent_secret_leaks", "behavior_rotate_leaked_credentials"],
                expected_response_contains=["rotate", "secret"],
                category="security",
            ),
            BenchmarkExample(
                example_id="ba-005",
                prompt="How do I create a reusable package for our shared utilities?",
                expected_behaviors=["behavior_extract_standalone_package"],
                expected_response_contains=["packages/", "pyproject.toml"],
                category="architecture",
            ),
        ]

        return Benchmark(
            name="behavior_adherence",
            description="Default benchmark for testing behavior-conditioned responses",
            examples=examples,
            version="1.0",
            created_at=datetime.utcnow(),
        )


def generate_benchmark_from_agents_md(
    agents_md_path: str,
    *,
    examples_per_behavior: int = 3,
    output_path: Optional[str] = None,
) -> Benchmark:
    """Generate a benchmark from AGENTS.md behaviors.

    Parses the AGENTS.md file to extract behavior definitions and
    generates evaluation examples for each behavior.

    Args:
        agents_md_path: Path to AGENTS.md file.
        examples_per_behavior: Number of examples per behavior.
        output_path: Optional path to save benchmark JSON.

    Returns:
        Generated Benchmark.
    """
    with open(agents_md_path) as f:
        content = f.read()

    # Parse behaviors from markdown
    behaviors: List[Dict[str, Any]] = []

    # Find behavior definitions (### `behavior_xxx` format)
    behavior_pattern = r"###\s*`(behavior_[a-z_]+)`\s*\n(.*?)(?=###|$)"
    matches = re.findall(behavior_pattern, content, re.DOTALL)

    for behavior_id, body in matches:
        # Extract "When" triggers
        when_match = re.search(r"\*\*When\*\*:\s*([^\n]+(?:\n-[^\n]+)*)", body)
        when_text = when_match.group(1).strip() if when_match else ""

        # Extract steps
        steps_match = re.search(r"\*\*Steps\*\*:\s*((?:\n\s*\d+\..*)+)", body)
        steps_text = steps_match.group(1).strip() if steps_match else ""

        behaviors.append({
            "behavior_id": behavior_id,
            "when": when_text,
            "steps": steps_text,
        })

    logger.info("Parsed %d behaviors from AGENTS.md", len(behaviors))

    # Generate examples
    examples: List[BenchmarkExample] = []

    prompt_templates = [
        "How do I {action}?",
        "What's the best practice for {action}?",
        "I need help with {action}. What should I do?",
    ]

    for behavior in behaviors:
        behavior_id = behavior["behavior_id"]
        when_text = behavior["when"]

        # Generate action from behavior name
        action = behavior_id.replace("behavior_", "").replace("_", " ")

        for i in range(examples_per_behavior):
            template = prompt_templates[i % len(prompt_templates)]
            prompt = template.format(action=action)

            # Add context from "when" triggers
            context = when_text[:200] if when_text else None

            examples.append(BenchmarkExample(
                example_id=f"{behavior_id}-{i+1:02d}",
                prompt=prompt,
                expected_behaviors=[behavior_id],
                context=context,
                category=action.split()[0] if action else "general",
            ))

    benchmark = Benchmark(
        name="agents_md_benchmark",
        description=f"Auto-generated from AGENTS.md ({len(behaviors)} behaviors)",
        examples=examples,
        version="1.0",
        created_at=datetime.utcnow(),
    )

    if output_path:
        benchmark.save(output_path)
        logger.info("Saved benchmark to %s (%d examples)", output_path, len(examples))

    return benchmark
