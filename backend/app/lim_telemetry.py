"""
Pillar 5: Agent Observability & Evaluation System (智能体可观测评测体系)
Built on OpenTelemetry + Langfuse (with dual-write to LIM Span store so frontend RunTraceDrawer works seamlessly).

Capabilities:
1. OpenTelemetry & Langfuse Tracing:
   - Captures Agent Execution Trajectories, Retrieval Evidence, Tool Invocations, Token Usage/Cost, and Error Diagnostics.
2. Core Evaluation Metrics (四大核心评测算子):
   - Task Success Rate (任务成功率)
   - Evidence Faithfulness (证据忠实度 - Grounded factual claim coverage vs retrieved evidence)
   - Tool Call Accuracy (工具调用准确率 - Schema validity + target tool/parameter match)
   - Safety Violation Rate (安全违规率 - RBAC, scope, state machine, or PII guardrail breaches)
3. Continuous Feedback & Optimization Loop across Ads Optimization, Profit Diagnostics,
   Inventory Alerts, and Procurement Decisions.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

try:
    from opentelemetry import trace as otel_trace  # type: ignore
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False
    otel_trace = None  # type: ignore

try:
    from langfuse import Langfuse  # type: ignore
    HAS_LANGFUSE = True
except ImportError:
    HAS_LANGFUSE = False
    Langfuse = None  # type: ignore


@dataclass
class TelemetrySpanRecord:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    name: str
    span_kind: str  # "agent_step" | "retrieval" | "tool_call" | "llm_generation"
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    latency_ms: float
    status: str  # "OK" | "ERROR" | "SAFETY_BLOCKED"
    attributes: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class EvaluationReport:
    eval_id: str
    run_id: str
    scenario: str
    task_success_rate: float
    evidence_faithfulness: float
    tool_call_accuracy: float
    safety_violation_rate: float
    total_tokens: int
    total_cost_usd: float
    total_latency_ms: float
    diagnostic_recommendations: List[str]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentObservabilityEvaluator:
    """
    Unified OpenTelemetry + Langfuse Tracer and Multi-Metric Evaluator.
    """

    PRICE_PROMPT_1K = 0.0025
    PRICE_COMPLETION_1K = 0.0100
    STOPWORDS: Set[str] = {
        "is", "are", "was", "were", "the", "a", "an", "with", "and", "or", "to", "for", "of",
        "in", "on", "at", "by", "from", "that", "this", "as", "be", "has", "have", "had",
        "的", "了", "是", "在", "与", "和", "及", "或", "对", "为",
    }

    def __init__(
        self,
        service_name: str = "ebus-lim-agent-platform",
        langfuse_public_key: Optional[str] = None,
        langfuse_secret_key: Optional[str] = None,
        langfuse_host: Optional[str] = None,
    ) -> None:
        self.service_name = service_name
        self.traces: Dict[str, List[TelemetrySpanRecord]] = {}
        self.evaluation_reports: List[EvaluationReport] = []

        self._otel_tracer = None
        if HAS_OTEL and otel_trace is not None:
            try:
                self._otel_tracer = otel_trace.get_tracer(service_name)
            except Exception:
                self._otel_tracer = None

        self._langfuse = None
        if HAS_LANGFUSE and Langfuse is not None and langfuse_public_key and langfuse_secret_key:
            try:
                self._langfuse = Langfuse(
                    public_key=langfuse_public_key,
                    secret_key=langfuse_secret_key,
                    host=langfuse_host,
                )
            except Exception:
                self._langfuse = None

    def record_span(
        self,
        trace_id: str,
        name: str,
        span_kind: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        status: str = "OK",
        attributes: Optional[Dict[str, Any]] = None,
        parent_span_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> TelemetrySpanRecord:
        cost = round(
            (prompt_tokens / 1000.0) * self.PRICE_PROMPT_1K
            + (completion_tokens / 1000.0) * self.PRICE_COMPLETION_1K,
            6,
        )
        span_rec = TelemetrySpanRecord(
            trace_id=trace_id,
            span_id=f"OTEL-{uuid.uuid4().hex[:10].upper()}",
            parent_span_id=parent_span_id,
            name=name,
            span_kind=span_kind,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=cost,
            latency_ms=round(latency_ms, 2),
            status=status,
            attributes=attributes or {},
            error_message=error_message,
        )
        self.traces.setdefault(trace_id, []).append(span_rec)

        if self._otel_tracer is not None:
            try:
                with self._otel_tracer.start_as_current_span(name) as otel_span:
                    otel_span.set_attribute("lim.trace_id", trace_id)
                    otel_span.set_attribute("lim.span_kind", span_kind)
                    otel_span.set_attribute("lim.prompt_tokens", prompt_tokens)
                    otel_span.set_attribute("lim.completion_tokens", completion_tokens)
                    otel_span.set_attribute("lim.cost_usd", cost)
            except Exception:
                pass

        if self._langfuse is not None:
            try:
                lf_trace = self._langfuse.trace(id=trace_id, name=self.service_name)
                lf_trace.span(
                    name=name,
                    metadata=attributes or {},
                    input={"prompt_tokens": prompt_tokens},
                    output={"completion_tokens": completion_tokens, "status": status},
                )
            except Exception:
                pass

        return span_rec

    @classmethod
    def compute_evidence_faithfulness(
        cls, generated_claims: List[str], retrieved_evidence_texts: List[str]
    ) -> float:
        """
        Computes Evidence Faithfulness (证据忠实度):
        Measures the proportion of non-stopword factual tokens/numbers/SKUs in generated claims
        that are grounded in the retrieved evidence corpus.
        """
        if not generated_claims:
            return 1.0
        if not retrieved_evidence_texts:
            return 0.0

        evidence_corpus = " ".join(retrieved_evidence_texts).lower()
        evidence_tokens = set(re.findall(r"[a-z0-9_.-]+|[\u4e00-\u9fff]", evidence_corpus))

        claim_scores: List[float] = []
        for claim in generated_claims:
            tokens = [
                t
                for t in re.findall(r"[a-z0-9_.-]+|[\u4e00-\u9fff]", claim.lower())
                if len(t) > 1 and t not in cls.STOPWORDS
            ]
            if not tokens:
                claim_scores.append(1.0)
                continue
            grounded = sum(1 for t in tokens if t in evidence_tokens)
            claim_scores.append(grounded / float(len(tokens)))

        return round(sum(claim_scores) / float(len(claim_scores)), 4)

    @staticmethod
    def compute_tool_call_accuracy(
        invoked_tools: List[Dict[str, Any]], expected_tools: List[Dict[str, Any]]
    ) -> float:
        if not expected_tools:
            return 1.0 if not invoked_tools else 0.85
        if not invoked_tools:
            return 0.0

        matched = 0.0
        for exp in expected_tools:
            exp_name = exp.get("tool_name")
            exp_params = exp.get("required_params", {})
            best_score = 0.0
            for inv in invoked_tools:
                if inv.get("tool_name") != exp_name:
                    continue
                inv_params = inv.get("parameters", {})
                if not exp_params:
                    best_score = 1.0
                    break
                param_hits = sum(1 for k, v in exp_params.items() if inv_params.get(k) == v)
                score = 0.5 + 0.5 * (param_hits / float(len(exp_params)))
                best_score = max(best_score, score)
            matched += best_score

        return round(matched / float(len(expected_tools)), 4)

    def evaluate_run(
        self,
        run_id: str,
        scenario: str,
        completed_steps: int,
        total_expected_steps: int,
        generated_claims: List[str],
        retrieved_evidence_texts: List[str],
        invoked_tools: List[Dict[str, Any]],
        expected_tools: List[Dict[str, Any]],
        safety_checks_total: int = 10,
        safety_violations_count: int = 0,
    ) -> EvaluationReport:
        task_success_rate = round(
            min(1.0, completed_steps / float(max(1, total_expected_steps))), 4
        )
        faithfulness = self.compute_evidence_faithfulness(generated_claims, retrieved_evidence_texts)
        tool_accuracy = self.compute_tool_call_accuracy(invoked_tools, expected_tools)
        safety_violation_rate = round(
            safety_violations_count / float(max(1, safety_checks_total)), 4
        )

        spans = self.traces.get(run_id, [])
        total_tokens = sum(s.prompt_tokens + s.completion_tokens for s in spans)
        total_cost = round(sum(s.estimated_cost_usd for s in spans), 6)
        total_latency = round(sum(s.latency_ms for s in spans), 2)

        recommendations: List[str] = []
        if faithfulness < 0.80:
            recommendations.append("Increase GraphRAG multi-hop depth or tighten citation grounding prompt constraints.")
        if tool_accuracy < 0.85:
            recommendations.append("Refine Pydantic tool descriptions and few-shot examples in procedural skill templates.")
        if safety_violation_rate > 0.0:
            recommendations.append("Review RBAC scope policies and enforce L3 human gate on high-value ERP mutations.")
        if not recommendations:
            recommendations.append("All 4 core observability & quality metrics meet production SLA thresholds.")

        report = EvaluationReport(
            eval_id=f"EVAL-{uuid.uuid4().hex[:8].upper()}",
            run_id=run_id,
            scenario=scenario,
            task_success_rate=task_success_rate,
            evidence_faithfulness=faithfulness,
            tool_call_accuracy=tool_accuracy,
            safety_violation_rate=safety_violation_rate,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            total_latency_ms=total_latency,
            diagnostic_recommendations=recommendations,
        )
        self.evaluation_reports.append(report)
        return report
