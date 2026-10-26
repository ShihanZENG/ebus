"""
Comprehensive Test Suite for the 5 Core Technical Pillars & P0/P1 ERP Integration Guardrails:
1. Pillar 1: Language Intelligence Middleware (`lim_langgraph_orchestrator.py`)
2. Pillar 2: Temporal Knowledge Graph & Agentic GraphRAG (`lim_graphrag.py`)
3. Pillar 3: 4-Tier Agent Memory & Skill Governance (`lim_memory.py`)
4. Pillar 4: Trusted Execution Control Framework & ERP State Machine Guard (`lim_execution_guard.py`)
5. Pillar 5: Agent Observability & Evaluation System (`lim_telemetry.py`)
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.lim_execution_guard import (
    DeterministicERPStateMachineGuard,
    ExecutionContext,
    ExecutionStatus,
    RiskLevel,
    ToolDescriptor,
    TrustedExecutionController,
)
from app.lim_graphrag import AgenticGraphRAGRetriever, TemporalKnowledgeGraphEngine
from app.lim_langgraph_orchestrator import LangGraphMultiAgentOrchestrator, StateCheckpointStore
from app.lim_memory import HierarchicalMemoryManager, MemoryTier
from app.lim_telemetry import AgentObservabilityEvaluator


class TestFivePillarsPlatform(unittest.TestCase):
    def test_pillar1_langgraph_orchestrator_and_conflict_arbitration(self) -> None:
        store = StateCheckpointStore()
        orchestrator = LangGraphMultiAgentOrchestrator(checkpoint_store=store)

        # Scenario: Low stock cover (6 days < 10d threshold) + high ROAS (4.5) + large PO exceeding finance cap
        result = orchestrator.run(
            user_query="请对 SKU-UK-DRESS-001 进行商品、库存、采购、广告、财务联合诊断与经营决策",
            target_skus=["SKU-UK-DRESS-001"],
            shared_context={
                "available_qty": 120,
                "weighted_daily_sales": 20.0,  # 6.0 days of cover (<10d)
                "supplier_lead_time_days": 14,
                "safety_stock_days": 7,
                "unit_cost_gbp": 18.0,
                "current_roas": 4.5,           # AdsAgent wants +25% budget
                "max_procurement_budget": 5000.0,  # Finance cap < 580 units * 18 GBP (10,440 GBP)
                "net_margin_pct": 22.0,
            },
        )
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(len(result["routed_domains"]), 5)
        self.assertGreaterEqual(len(result["conflicts"]), 2)

        # Verify Conflict 1: Ads budget throttled due to low inventory cover
        ads_prop = result["proposals"]["ads"]["proposed_value"]
        self.assertTrue(ads_prop["arbitration_override"])
        self.assertLessEqual(ads_prop["budget_change_pct"], 0.0)

        # Verify Conflict 2: Procurement PO capped to Finance working capital ceiling
        proc_prop = result["proposals"]["procurement"]["proposed_value"]
        self.assertTrue(proc_prop["split_batch_delivery"])
        self.assertLessEqual(proc_prop["po_total_amount"], 5000.0)

        # Verify checkpoint persistence
        versions = store.list_versions(result["run_id"])
        self.assertGreaterEqual(len(versions), 2)

    def test_pillar2_temporal_graphrag_hybrid_retrieval(self) -> None:
        graph = TemporalKnowledgeGraphEngine()
        retriever = AgenticGraphRAGRetriever(graph_engine=graph)

        res = retriever.retrieve(
            query="SKU-UK-DRESS-001 库存断货预警与英国退货预占政策、供应商交期及广告投放诊断",
            seed_entities=["SKU-UK-DRESS-001"],
            as_of="2026-10-20T00:00:00Z",
            top_k=6,
        )
        self.assertEqual(len(res["retrieval_plan"]["activated_channels"]), 4)
        self.assertGreater(res["graph_paths_traversed"], 0)
        self.assertGreaterEqual(len(res["ranked_evidence"]), 4)
        top_entity_ids = [item["entity_id"] for item in res["ranked_evidence"]]
        self.assertIn("SKU-UK-DRESS-001", top_entity_ids)

    def test_pillar3_four_tier_memory_decay_conflict_and_skill_distillation(self) -> None:
        mem = HierarchicalMemoryManager(forgetting_threshold=0.30)
        t0 = 1700000000.0

        rec1, conf1 = mem.store_memory(
            tier=MemoryTier.SEMANTIC,
            entity_key="SUP-HZ-SILK-01",
            attribute_key="lead_time_days",
            content={"days": 14},
            base_confidence=0.80,
            now_epoch=t0,
        )
        self.assertIsNone(conf1)

        # Introduce conflicting semantic observation with higher confidence
        rec2, conf2 = mem.store_memory(
            tier=MemoryTier.SEMANTIC,
            entity_key="SUP-HZ-SILK-01",
            attribute_key="lead_time_days",
            content={"days": 10},
            base_confidence=0.92,
            now_epoch=t0 + 3600,
        )
        self.assertIsNotNone(conf2)
        self.assertEqual(conf2["resolution"], "SUPERSEDED_BY_NEW")

        # Verify time decay and active forgetting sweep after 60 days
        sweep = mem.run_forgetting_sweep(now_epoch=t0 + 60 * 86400)
        self.assertGreaterEqual(sweep["forgotten_count"], 1)

        # Verify trajectory-to-Skill distillation & version rollback
        s_v0 = mem.distill_trajectory_to_skill(
            skill_name="uk_dress_stockout_joint_mitigation",
            domain="procurement_ads_joint",
            trigger_pattern="days_of_cover < 10 and roas > 3.5",
            episodic_trajectory=[{"step": 1, "action": "throttle_ads"}, {"step": 2, "action": "create_staged_po"}],
            run_id="RUN-001",
            reward_score=0.94,
        )
        self.assertIsNotNone(s_v0)
        self.assertEqual(s_v0.version, "v1.0")

        s_v1 = mem.distill_trajectory_to_skill(
            skill_name="uk_dress_stockout_joint_mitigation",
            domain="procurement_ads_joint",
            trigger_pattern="days_of_cover < 8 and roas > 3.5",
            episodic_trajectory=[{"step": 1, "action": "pause_ads"}, {"step": 2, "action": "expedite_air_po"}],
            run_id="RUN-002",
            reward_score=0.96,
        )
        self.assertEqual(s_v1.version, "v1.1")
        rolled = mem.rollback_skill_version("uk_dress_stockout_joint_mitigation", "v1.0")
        self.assertEqual(rolled.status, "ACTIVE")

    def test_pillar4_trusted_execution_and_p0_p1_erp_guards(self) -> None:
        guard = DeterministicERPStateMachineGuard(hold_ttl_minutes=30)
        controller = TrustedExecutionController(state_guard=guard)

        # Register a guarded shipment approval tool
        controller.register_tool(
            ToolDescriptor(
                tool_name="approve_order_shipment",
                domain="orders",
                required_permission="orders:approve_shipment",
                default_risk_level=RiskLevel.L2_GUARDED_WRITE,
                required_fields={"order_id": str, "shop_id": str},
                handler=lambda p: guard.approve_order_for_shipment(p["order_id"]),
            )
        )

        # P0-01 & P0-02: Checkout atomically holds stock and writes OMS outbox event
        checkout_res = guard.checkout_with_atomic_hold_and_outbox(
            order_id="ORD-2026-001",
            sku_id="SKU-UK-DRESS-001",
            qty=5,
            shop_id="shop-uk-01",
            amount_gbp=249.50,
            idempotency_key="IDEM-CHK-001",
        )
        self.assertEqual(guard.inventory_ledger["SKU-UK-DRESS-001"]["available_qty"], 115)
        self.assertEqual(guard.inventory_ledger["SKU-UK-DRESS-001"]["reserved_qty"], 5)
        self.assertEqual(len(guard.oms_outbox_queue), 1)

        admin_ctx = ExecutionContext(
            user_id="usr-admin",
            roles=["finance_admin"],
            allowed_shops=["shop-uk-01"],
            allowed_warehouses=["wh-uk-main"],
        )

        # P0-03 Gate: Attempting to approve shipment while payment_status == "not_charged" MUST be blocked
        blocked_audit = controller.execute_tool(
            "approve_order_shipment",
            {"order_id": "ORD-2026-001", "shop_id": "shop-uk-01"},
            ctx=admin_ctx,
        )
        self.assertEqual(blocked_audit.status, ExecutionStatus.BLOCKED_BY_STATE_MACHINE.value)

        # P1-04: Register verified payment with idempotency
        pay1 = guard.register_payment_with_idempotency("ORD-2026-001", "TXN-STRIPE-999", 249.50)
        self.assertFalse(pay1["idempotent_replay"])
        pay2 = guard.register_payment_with_idempotency("ORD-2026-001", "TXN-STRIPE-999", 249.50)
        self.assertTrue(pay2["idempotent_replay"])

        # Now shipment approval succeeds and reuses existing hold without double deduction
        ok_audit = controller.execute_tool(
            "approve_order_shipment",
            {"order_id": "ORD-2026-001", "shop_id": "shop-uk-01"},
            ctx=admin_ctx,
            idempotency_key="IDEM-SHIP-001",
        )
        self.assertEqual(ok_audit.status, ExecutionStatus.EXECUTED.value)
        self.assertEqual(guard.inventory_ledger["SKU-UK-DRESS-001"]["available_qty"], 115)

        # Idempotent replay on tool execution
        replay_audit = controller.execute_tool(
            "approve_order_shipment",
            {"order_id": "ORD-2026-001", "shop_id": "shop-uk-01"},
            ctx=admin_ctx,
            idempotency_key="IDEM-SHIP-001",
        )
        self.assertEqual(replay_audit.status, ExecutionStatus.IDEMPOTENT_REPLAY.value)

    def test_pillar5_observability_and_four_evaluation_metrics(self) -> None:
        evaluator = AgentObservabilityEvaluator()
        run_id = "RUN-EVAL-001"
        evaluator.record_span(
            trace_id=run_id,
            name="langgraph.supervisor",
            span_kind="agent_step",
            prompt_tokens=420,
            completion_tokens=180,
            latency_ms=340.5,
        )
        report = evaluator.evaluate_run(
            run_id=run_id,
            scenario="ads_inventory_procurement_joint_optimization",
            completed_steps=5,
            total_expected_steps=5,
            generated_claims=["SKU-UK-DRESS-001 available_qty is 120 with 6.0 days_of_cover and ROAS 4.2"],
            retrieved_evidence_texts=[
                "SKU-UK-DRESS-001 InventorySnapshot available_qty 120 days_of_cover 6.0 AdCampaign ROAS 4.2"
            ],
            invoked_tools=[{"tool_name": "throttle_ads_budget", "parameters": {"sku_id": "SKU-UK-DRESS-001"}}],
            expected_tools=[{"tool_name": "throttle_ads_budget", "required_params": {"sku_id": "SKU-UK-DRESS-001"}}],
            safety_checks_total=12,
            safety_violations_count=0,
        )
        self.assertEqual(report.task_success_rate, 1.0)
        self.assertGreaterEqual(report.evidence_faithfulness, 0.85)
        self.assertEqual(report.tool_call_accuracy, 1.0)
        self.assertEqual(report.safety_violation_rate, 0.0)
        self.assertEqual(report.total_tokens, 600)


if __name__ == "__main__":
    unittest.main()