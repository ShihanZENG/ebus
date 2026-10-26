"""Authenticated LIM v2 sandbox endpoints.

These endpoints exercise the imported five-pillar algorithms. They do not
write ERP orders, inventory, payments, or production LIM governance records.
"""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import models as m
from .lim_graphrag import AgenticGraphRAGRetriever, TemporalKnowledgeGraphEngine
from .lim_execution_guard import DeterministicERPStateMachineGuard
from .lim_langgraph_orchestrator import LangGraphMultiAgentOrchestrator, StateCheckpointStore
from .lim_memory import HierarchicalMemoryManager, MemoryTier
from .lim_telemetry import AgentObservabilityEvaluator
from .security import require, require_scope, session_db


router = APIRouter(prefix='/api/v1/lim/v2', tags=['LIM 五大能力沙盘'])
checkpoint_store = StateCheckpointStore()
orchestrator = LangGraphMultiAgentOrchestrator(checkpoint_store=checkpoint_store)
graph_retriever = AgenticGraphRAGRetriever(graph_engine=TemporalKnowledgeGraphEngine())
memory = HierarchicalMemoryManager()
evaluator = AgentObservabilityEvaluator()


class OrchestrateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_query: str = Field(min_length=1, max_length=2000)
    shop_id: str = Field(min_length=1, max_length=36)
    warehouse_id: str = Field(min_length=1, max_length=36)
    target_skus: list[str] = Field(default_factory=list, max_length=20)
    shared_context: dict[str, Any] = Field(default_factory=dict)


class GraphRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=2000)
    seed_entities: list[str] = Field(default_factory=list, max_length=20)
    as_of: str | None = None
    top_k: int = Field(default=8, ge=1, le=50)


class MemoryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tier: MemoryTier
    shop_id: str = Field(min_length=1, max_length=36)
    entity_key: str = Field(min_length=1, max_length=120)
    attribute_key: str = Field(min_length=1, max_length=120)
    content: dict[str, Any]
    base_confidence: float = Field(default=0.85, ge=0, le=1)


class SkillRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    skill_name: str = Field(min_length=1, max_length=120)
    domain: str = Field(min_length=1, max_length=80)
    trigger_pattern: str = Field(min_length=1, max_length=500)
    episodic_trajectory: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    run_id: str = Field(min_length=1, max_length=80)
    reward_score: float = Field(ge=0, le=1)


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_id: str = Field(min_length=1, max_length=80)
    scenario: str = Field(min_length=1, max_length=200)
    completed_steps: int = Field(ge=0)
    total_expected_steps: int = Field(gt=0)
    generated_claims: list[str] = Field(default_factory=list, max_length=100)
    retrieved_evidence_texts: list[str] = Field(default_factory=list, max_length=100)
    invoked_tools: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    expected_tools: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    safety_checks_total: int = Field(default=10, gt=0)
    safety_violations_count: int = Field(default=0, ge=0)


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    available_qty: int = Field(default=10, ge=0, le=1_000_000)
    checkout_qty: int = Field(default=1, ge=1, le=1_000_000)
    payment_verified: bool = False


@router.post('/orchestrate')
def run_orchestration(req: OrchestrateRequest, db=Depends(session_db),
                      user=Depends(require('assistant:read'))):
    require_scope(user, shop_id=req.shop_id, warehouse_id=req.warehouse_id)
    if db.get(m.Shop, req.shop_id) is None or db.get(m.Warehouse, req.warehouse_id) is None:
        raise HTTPException(404, '店铺或仓库不存在')
    result = orchestrator.run(
        user_query=req.user_query, tenant_id=user.id, shop_id=req.shop_id,
        warehouse_id=req.warehouse_id, target_skus=req.target_skus,
        shared_context=req.shared_context,
    )
    return {'mode': 'sandbox', 'result': dict(result)}


@router.post('/graphrag/retrieve')
def retrieve_graph(req: GraphRequest, user=Depends(require('assistant:read'))):
    # The packaged graph contains example data only. Never report it as ERP evidence.
    return {'mode': 'sandbox', 'result': graph_retriever.retrieve(
        query=req.query, seed_entities=req.seed_entities,
        as_of=req.as_of, top_k=req.top_k)}


@router.post('/memory/store')
def store_memory(req: MemoryRequest, db=Depends(session_db),
                 user=Depends(require('lim:manage'))):
    require_scope(user, shop_id=req.shop_id)
    if db.get(m.Shop, req.shop_id) is None:
        raise HTTPException(404, '店铺不存在')
    record, conflict = memory.store_memory(
        tier=req.tier, entity_key=req.entity_key,
        attribute_key=req.attribute_key, content=req.content,
        tenant_id=f'{user.id}:{req.shop_id}', base_confidence=req.base_confidence,
        verified_by_human=False,
    )
    return {'mode': 'sandbox', 'memory': asdict(record), 'conflict': conflict}


@router.post('/memory/distill-skill')
def distill_skill(req: SkillRequest, user=Depends(require('lim:manage'))):
    skill = memory.distill_trajectory_to_skill(
        skill_name=f'{user.id}:{req.skill_name}', domain=req.domain,
        trigger_pattern=req.trigger_pattern,
        episodic_trajectory=req.episodic_trajectory, run_id=req.run_id,
        reward_score=req.reward_score, human_approved=False,
    )
    if skill is None:
        raise HTTPException(422, '轨迹评分低于蒸馏阈值')
    return {'mode': 'sandbox', 'skill': asdict(skill)}


@router.post('/telemetry/evaluate')
def evaluate(req: EvaluationRequest, user=Depends(require('assistant:read'))):
    report = evaluator.evaluate_run(**req.model_dump())
    return {'mode': 'sandbox', 'report': asdict(report)}


@router.post('/execution/simulate')
def simulate_execution(req: ExecutionRequest, user=Depends(require('assistant:read'))):
    guard = DeterministicERPStateMachineGuard(hold_ttl_minutes=30)
    guard.inventory_ledger['SANDBOX-SKU'] = {
        'available_qty': req.available_qty, 'reserved_qty': 0,
    }
    try:
        checkout = guard.checkout_with_atomic_hold_and_outbox(
            order_id='SANDBOX-ORDER', sku_id='SANDBOX-SKU', qty=req.checkout_qty,
            shop_id='SANDBOX-SHOP', amount_gbp=1.0, idempotency_key='SANDBOX-CHECKOUT',
        )
    except ValueError as exc:
        return {'mode': 'sandbox', 'checkout_error': str(exc), 'shipment_allowed': False}
    if req.payment_verified:
        guard.register_payment_with_idempotency('SANDBOX-ORDER', 'SANDBOX-TXN', 1.0)
    try:
        shipment = guard.approve_order_for_shipment('SANDBOX-ORDER')
        return {'mode': 'sandbox', 'checkout': checkout, 'shipment_allowed': True,
                'shipment': shipment}
    except PermissionError as exc:
        return {'mode': 'sandbox', 'checkout': checkout, 'shipment_allowed': False,
                'gate_reason': str(exc)}
