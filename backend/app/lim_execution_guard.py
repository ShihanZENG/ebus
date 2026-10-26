"""
Pillar 4: Trusted Execution Control Framework (可信执行控制框架)
Decouples probabilistic LLM reasoning from deterministic ERP business execution.

Capabilities:
1. Typed Tool Calling & Schema Enforcement (类型化工具调用):
   - Validates tool parameters against strict JSON/type schemas before execution.
2. Fine-Grained RBAC & Tenant/Shop/Warehouse Scope Isolation (RBAC 细粒度权限与作用域隔离):
   - Enforces role permissions and shop/warehouse boundaries.
3. Risk Grading (L0 ~ L3) & Human-in-the-Loop Approval Gate (风险分级与人工审批):
   - L0 (Read-Only): Instant execution
   - L1 (Low-Risk Draft/Tagging): Automated execution with audit log
   - L2 (Medium-Risk Ad Budget/Price/Inventory Hold within limits): Rule-checked execution
   - L3 (High-Risk PO Approval, Large Inventory Adjustment, Financial Payout/Refund): Mandatory Human Gate
4. Deterministic Business State Machine Guard (确定性业务规则与状态机约束):
   - Also closes P0-01 (Order Sovereignty Outbox), P0-02 (Atomic Inventory Hold with 30m TTL),
     P0-03 (Payment Evidence Gate before shipment), and P1-04 (Payment Transaction Idempotency).
5. Idempotency Control, Failure Recovery/Compensation & Execution Audit (幂等控制、失败恢复与执行审计).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


class RiskLevel(str, Enum):
    L0_READ_ONLY = "L0_READ_ONLY"
    L1_LOW_RISK_DRAFT = "L1_LOW_RISK_DRAFT"
    L2_GUARDED_WRITE = "L2_GUARDED_WRITE"
    L3_HIGH_RISK_HUMAN_GATE = "L3_HIGH_RISK_HUMAN_GATE"


class ExecutionStatus(str, Enum):
    EXECUTED = "EXECUTED"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
    WAITING_HUMAN_APPROVAL = "WAITING_HUMAN_APPROVAL"
    BLOCKED_BY_RBAC = "BLOCKED_BY_RBAC"
    BLOCKED_BY_STATE_MACHINE = "BLOCKED_BY_STATE_MACHINE"
    ROLLED_BACK_COMPENSATED = "ROLLED_BACK_COMPENSATED"
    FAILED = "FAILED"


@dataclass
class ExecutionContext:
    user_id: str
    roles: List[str]
    allowed_shops: List[str]
    allowed_warehouses: List[str]
    tenant_id: str = "tenant-default"


@dataclass
class ToolDescriptor:
    tool_name: str
    domain: str
    required_permission: str
    default_risk_level: RiskLevel
    required_fields: Dict[str, type]
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]
    compensator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None


@dataclass
class AuditTrailEntry:
    audit_id: str
    idempotency_key: str
    tool_name: str
    user_id: str
    risk_level: str
    status: str
    input_payload: Dict[str, Any]
    output_payload: Dict[str, Any]
    reason: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DeterministicERPStateMachineGuard:
    """
    Enforces deterministic ERP business rules & state transitions across Order, Inventory,
    Procurement, and Finance operations (closing P0-01, P0-02, P0-03, P1-01, P1-04).
    """

    VALID_ORDER_TRANSITIONS: Dict[str, Set[str]] = {
        "CREATED": {"HOLD_RESERVED", "CANCELLED"},
        "HOLD_RESERVED": {"PAID_VERIFIED", "EXPIRED_RELEASED", "CANCELLED"},
        "PAID_VERIFIED": {"APPROVED_FOR_SHIPMENT", "REFUNDED"},
        "APPROVED_FOR_SHIPMENT": {"SHIPPED", "CANCELLED"},
        "SHIPPED": {"COMPLETED", "RETURNED"},
    }

    def __init__(self, hold_ttl_minutes: int = 30) -> None:
        self.hold_ttl_minutes = hold_ttl_minutes
        self.inventory_ledger: Dict[str, Dict[str, int]] = {
            "SKU-UK-DRESS-001": {"available_qty": 120, "reserved_qty": 0}
        }
        self.active_holds: Dict[str, Dict[str, Any]] = {}
        self.order_states: Dict[str, Dict[str, Any]] = {}
        self.payment_transactions: Dict[str, Dict[str, Any]] = {}
        self.oms_outbox_queue: List[Dict[str, Any]] = []

    def checkout_with_atomic_hold_and_outbox(
        self,
        order_id: str,
        sku_id: str,
        qty: int,
        shop_id: str,
        amount_gbp: float,
        idempotency_key: str,
        now_utc: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Addresses P0-01 (Single Order Sovereignty + OMS Outbox Contract)
        and P0-02 (Atomic Inventory Hold before Checkout Success with 30-min TTL).
        """
        now_dt = now_utc or datetime.now(timezone.utc)
        stock = self.inventory_ledger.setdefault(sku_id, {"available_qty": 0, "reserved_qty": 0})
        if qty <= 0 or stock["available_qty"] < qty:
            raise ValueError(
                f"INSUFFICIENT_AVAILABLE_STOCK: requested {qty} of {sku_id}, available {stock['available_qty']}"
            )

        # Atomic inventory reservation in same unit of work
        stock["available_qty"] -= qty
        stock["reserved_qty"] += qty
        expires_at = (now_dt + timedelta(minutes=self.hold_ttl_minutes)).isoformat()

        hold_record = {
            "hold_id": f"HOLD-{order_id}",
            "order_id": order_id,
            "sku_id": sku_id,
            "qty": qty,
            "status": "ACTIVE",
            "expires_at": expires_at,
        }
        self.active_holds[order_id] = hold_record

        order_record = {
            "order_id": order_id,
            "shop_id": shop_id,
            "sku_id": sku_id,
            "qty": qty,
            "amount_gbp": amount_gbp,
            "state": "HOLD_RESERVED",
            "payment_status": "not_charged",
            "payment_verified": False,
            "hold_id": hold_record["hold_id"],
            "created_at": now_dt.isoformat(),
        }
        self.order_states[order_id] = order_record

        # P0-01 & P1-01: Enqueue versioned handoff event to Standalone OMS Outbox Queue
        outbox_event = {
            "event_id": f"EVT-{uuid.uuid4().hex[:8].upper()}",
            "contract_version": "v1.1",
            "idempotency_key": idempotency_key,
            "authority_source": "ERP_MAIN_BACKEND",
            "target_system": "STANDALONE_OMS",
            "event_type": "ORDER_CREATED_AND_RESERVED",
            "order_payload": order_record,
            "sync_status": "PENDING",
            "retry_count": 0,
        }
        self.oms_outbox_queue.append(outbox_event)
        return {"order": order_record, "hold": hold_record, "outbox_event": outbox_event}

    def release_expired_or_cancelled_hold(
        self, order_id: str, reason: str = "TIMEOUT_EXPIRED"
    ) -> Dict[str, Any]:
        """Releases reserved inventory back to available_qty on timeout or buyer cancellation (P0-02 & P1-03)."""
        hold = self.active_holds.get(order_id)
        order = self.order_states.get(order_id)
        if not hold or hold["status"] != "ACTIVE":
            return {"order_id": order_id, "released": False, "reason": "NO_ACTIVE_HOLD"}

        sku_id = hold["sku_id"]
        qty = hold["qty"]
        stock = self.inventory_ledger[sku_id]
        stock["reserved_qty"] = max(0, stock["reserved_qty"] - qty)
        stock["available_qty"] += qty
        hold["status"] = "RELEASED"
        if order:
            order["state"] = "EXPIRED_RELEASED" if reason == "TIMEOUT_EXPIRED" else "CANCELLED"
        return {"order_id": order_id, "released": True, "restored_qty": qty, "new_state": order["state"] if order else None}

    def register_payment_with_idempotency(
        self, order_id: str, external_transaction_id: str, amount_gbp: float, signature_verified: bool = True
    ) -> Dict[str, Any]:
        """
        Addresses P0-03 (Payment Evidence Gate) & P1-04 (Idempotent External Transaction ID constraint).
        """
        if external_transaction_id in self.payment_transactions:
            existing = self.payment_transactions[external_transaction_id]
            return {"idempotent_replay": True, "payment_record": existing}

        if not signature_verified:
            raise ValueError("PAYMENT_SIGNATURE_VERIFICATION_FAILED")

        order = self.order_states.get(order_id)
        if not order:
            raise ValueError(f"ORDER_NOT_FOUND: {order_id}")

        payment_record = {
            "payment_id": f"PAY-{uuid.uuid4().hex[:8].upper()}",
            "order_id": order_id,
            "external_transaction_id": external_transaction_id,
            "amount_gbp": amount_gbp,
            "signature_verified": True,
            "status": "CHARGED_VERIFIED",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.payment_transactions[external_transaction_id] = payment_record
        order["payment_status"] = "paid"
        order["payment_verified"] = True
        order["state"] = "PAID_VERIFIED"
        return {"idempotent_replay": False, "payment_record": payment_record}

    def approve_order_for_shipment(self, order_id: str) -> Dict[str, Any]:
        """
        Enforces P0-03 Gate: Blocks shipment approval if `payment_status == 'not_charged'` or unverified,
        and reuses checkout hold (P0-02) without double-deducting inventory.
        """
        order = self.order_states.get(order_id)
        if not order:
            raise ValueError(f"ORDER_NOT_FOUND: {order_id}")

        if order.get("payment_status") == "not_charged" or not order.get("payment_verified"):
            raise PermissionError(
                f"PAYMENT_GATE_BLOCKED: Order {order_id} has payment_status='{order.get('payment_status')}' "
                "and cannot transition to APPROVED_FOR_SHIPMENT without verified payment evidence."
            )

        allowed = self.VALID_ORDER_TRANSITIONS.get(order["state"], set())
        if "APPROVED_FOR_SHIPMENT" not in allowed:
            raise ValueError(f"INVALID_STATE_TRANSITION: {order['state']} -> APPROVED_FOR_SHIPMENT")

        hold = self.active_holds.get(order_id)
        if not hold or hold["status"] != "ACTIVE":
            raise ValueError(f"MISSING_ACTIVE_INVENTORY_HOLD for order {order_id}")

        # Reuse existing reservation hold without double deduction
        hold["status"] = "COMMITTED_TO_SHIPMENT"
        order["state"] = "APPROVED_FOR_SHIPMENT"
        return {"order_id": order_id, "state": order["state"], "hold_status": hold["status"]}


class TrustedExecutionController:
    """
    Unified Agent Execution Control Framework:
    Integrates Typed Tool Validation, Fine-Grained RBAC, Risk Grading (L0-L3),
    Human Approval Gate, Idempotency Cache, Automatic Failure Compensation, and Audit Logging.
    """

    ROLE_PERMISSIONS: Dict[str, Set[str]] = {
        "viewer": {"catalog:read", "inventory:read", "orders:read"},
        "operator": {
            "catalog:read",
            "inventory:read",
            "orders:read",
            "ads:write",
            "inventory:hold",
            "procurement:draft",
        },
        "finance_admin": {
            "catalog:read",
            "inventory:read",
            "orders:read",
            "ads:write",
            "inventory:hold",
            "procurement:draft",
            "procurement:approve",
            "finance:write",
            "orders:approve_shipment",
        },
    }

    def __init__(self, state_guard: Optional[DeterministicERPStateMachineGuard] = None) -> None:
        self.state_guard = state_guard or DeterministicERPStateMachineGuard()
        self.tools: Dict[str, ToolDescriptor] = {}
        self.idempotency_store: Dict[str, AuditTrailEntry] = {}
        self.pending_approvals: Dict[str, Dict[str, Any]] = {}
        self.audit_log: List[AuditTrailEntry] = []

    def register_tool(self, descriptor: ToolDescriptor) -> None:
        self.tools[descriptor.tool_name] = descriptor

    def _has_permission(self, ctx: ExecutionContext, required_perm: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
        granted_perms: Set[str] = set()
        for r in ctx.roles:
            granted_perms |= self.ROLE_PERMISSIONS.get(r, set())
        if required_perm not in granted_perms:
            return False, f"Missing permission '{required_perm}' for roles {ctx.roles}"

        shop_id = payload.get("shop_id")
        if shop_id and ctx.allowed_shops and shop_id not in ctx.allowed_shops:
            return False, f"Shop scope violation: '{shop_id}' not in allowed_shops {ctx.allowed_shops}"

        warehouse_id = payload.get("warehouse_id")
        if warehouse_id and ctx.allowed_warehouses and warehouse_id not in ctx.allowed_warehouses:
            return False, f"Warehouse scope violation: '{warehouse_id}' not in allowed_warehouses {ctx.allowed_warehouses}"

        return True, "OK"

    def evaluate_dynamic_risk(self, descriptor: ToolDescriptor, payload: Dict[str, Any]) -> RiskLevel:
        # Escalate to L3 Human Gate when financial thresholds are exceeded
        po_amount = float(payload.get("po_total_amount", 0.0))
        budget_delta = abs(float(payload.get("budget_change_pct", 0.0)))
        if po_amount >= 5000.0 or budget_delta >= 30.0:
            return RiskLevel.L3_HIGH_RISK_HUMAN_GATE
        return descriptor.default_risk_level

    def execute_tool(
        self,
        tool_name: str,
        payload: Dict[str, Any],
        ctx: ExecutionContext,
        idempotency_key: Optional[str] = None,
        human_approved: bool = False,
    ) -> AuditTrailEntry:
        idem_key = idempotency_key or hashlib.sha256(
            f"{tool_name}:{ctx.user_id}:{json.dumps(payload, sort_keys=True, default=str)}".encode("utf-8")
        ).hexdigest()[:20]

        # 1. Idempotency check
        if idem_key in self.idempotency_store and not human_approved:
            cached = self.idempotency_store[idem_key]
            replay_entry = AuditTrailEntry(
                audit_id=f"AUD-{uuid.uuid4().hex[:8].upper()}",
                idempotency_key=idem_key,
                tool_name=tool_name,
                user_id=ctx.user_id,
                risk_level=cached.risk_level,
                status=ExecutionStatus.IDEMPOTENT_REPLAY.value,
                input_payload=payload,
                output_payload=cached.output_payload,
                reason="Returned cached result from idempotency key.",
            )
            self.audit_log.append(replay_entry)
            return replay_entry

        descriptor = self.tools.get(tool_name)
        if not descriptor:
            raise KeyError(f"Unregistered tool: {tool_name}")

        # 2. Typed parameter validation
        for field_name, expected_type in descriptor.required_fields.items():
            if field_name not in payload or not isinstance(payload[field_name], expected_type):
                raise TypeError(
                    f"Typed tool validation failed on '{tool_name}': field '{field_name}' must be {expected_type.__name__}"
                )

        # 3. RBAC & Scope Isolation check
        allowed, rbac_reason = self._has_permission(ctx, descriptor.required_permission, payload)
        risk_level = self.evaluate_dynamic_risk(descriptor, payload)
        if not allowed:
            entry = AuditTrailEntry(
                audit_id=f"AUD-{uuid.uuid4().hex[:8].upper()}",
                idempotency_key=idem_key,
                tool_name=tool_name,
                user_id=ctx.user_id,
                risk_level=risk_level.value,
                status=ExecutionStatus.BLOCKED_BY_RBAC.value,
                input_payload=payload,
                output_payload={},
                reason=rbac_reason,
            )
            self.audit_log.append(entry)
            return entry

        # 4. L3 Risk Grading -> Human-in-the-Loop Approval Gate
        if risk_level == RiskLevel.L3_HIGH_RISK_HUMAN_GATE and not human_approved:
            approval_id = f"APPR-{uuid.uuid4().hex[:8].upper()}"
            self.pending_approvals[approval_id] = {
                "approval_id": approval_id,
                "tool_name": tool_name,
                "payload": payload,
                "context": asdict(ctx),
                "idempotency_key": idem_key,
            }
            entry = AuditTrailEntry(
                audit_id=f"AUD-{uuid.uuid4().hex[:8].upper()}",
                idempotency_key=idem_key,
                tool_name=tool_name,
                user_id=ctx.user_id,
                risk_level=risk_level.value,
                status=ExecutionStatus.WAITING_HUMAN_APPROVAL.value,
                input_payload=payload,
                output_payload={"approval_id": approval_id},
                reason="L3 high-risk operation requires human approval before ERP execution.",
            )
            self.audit_log.append(entry)
            return entry

        # 5. Execute tool handler with deterministic state guard & failure compensation
        try:
            output = descriptor.handler(payload)
            entry = AuditTrailEntry(
                audit_id=f"AUD-{uuid.uuid4().hex[:8].upper()}",
                idempotency_key=idem_key,
                tool_name=tool_name,
                user_id=ctx.user_id,
                risk_level=risk_level.value,
                status=ExecutionStatus.EXECUTED.value,
                input_payload=payload,
                output_payload=output,
                reason="Executed successfully under trusted guard.",
            )
            self.idempotency_store[idem_key] = entry
            self.audit_log.append(entry)
            return entry
        except (PermissionError, ValueError) as state_err:
            entry = AuditTrailEntry(
                audit_id=f"AUD-{uuid.uuid4().hex[:8].upper()}",
                idempotency_key=idem_key,
                tool_name=tool_name,
                user_id=ctx.user_id,
                risk_level=risk_level.value,
                status=ExecutionStatus.BLOCKED_BY_STATE_MACHINE.value,
                input_payload=payload,
                output_payload={},
                reason=str(state_err),
            )
            self.audit_log.append(entry)
            return entry
        except Exception as exc:
            comp_result = {}
            if descriptor.compensator is not None:
                try:
                    comp_result = descriptor.compensator(payload)
                except Exception:
                    pass
            entry = AuditTrailEntry(
                audit_id=f"AUD-{uuid.uuid4().hex[:8].upper()}",
                idempotency_key=idem_key,
                tool_name=tool_name,
                user_id=ctx.user_id,
                risk_level=risk_level.value,
                status=(
                    ExecutionStatus.ROLLED_BACK_COMPENSATED.value
                    if comp_result
                    else ExecutionStatus.FAILED.value
                ),
                input_payload=payload,
                output_payload={"compensation": comp_result},
                reason=f"Execution failed: {exc}",
            )
            self.audit_log.append(entry)
            return entry
