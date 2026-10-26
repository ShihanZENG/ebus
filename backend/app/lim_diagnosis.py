"""LangGraph 多智能体联合诊断。

把既有只读「业务证据工具」(backend.app.business_evidence_tools) 编排成一个多智能体图：

    supervisor ──► [orders_agent, ads_agent, inventory_alignment_agent, payments_agent]  (并行)
                 └──► synthesis 汇总 evidence_refs / gaps / findings，给出权限缺口与结论

设计约定（与既有 LIM 运行时一致）：
- 每个 worker 直接调用 business_evidence_tools 的适配器，**不重复实现**证据采集逻辑。
- 权限不足时证据工具返回 `PERMISSION_REQUIRED` gap，worker 标记为 `denied` 而非抛错（优雅降级）。
- 证据工具内部异常（如 scope / 日期非法）被 worker 捕获并标记为 `error`，不中断整图。
- 本模块只做**只读诊断**：不写业务数据、不调用 LLM，不引入不确定的外部依赖。
- 「任务重启 / 恢复」（checkpoint 持久化 + resume）按计划**留待下一步**；本步用内存图同步执行，
  诊断记录仅存于进程内存（DIAGNOSES），重启后清空。
"""
from __future__ import annotations

import operator
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from . import business_evidence_tools as bet
from .lim_errors import LimRuntimeError

# 领域 → 智能体节点名（也是 supervisor 的派发目标）。
DOMAIN_AGENTS: dict[str, str] = {
    'orders': 'orders_agent',
    'ads': 'ads_agent',
    'inventory_alignment': 'inventory_alignment_agent',
    'payments': 'payments_agent',
}
ALL_DOMAINS = list(DOMAIN_AGENTS)

# 领域 → 复用的证据工具函数名（必须存在于 business_evidence_tools）。
DOMAIN_TOOL: dict[str, str] = {
    'orders': 'read_order_period_summary',
    'ads': 'read_ad_campaign_performance',
    'inventory_alignment': 'read_ads_inventory_alignment',
    'payments': 'read_recorded_payments',
}

# 进程内诊断记录（本步不落库）。
DIAGNOSES: dict[str, dict] = {}
_MAX_MEMORY_RECORDS = 50


class DiagnosisState(TypedDict):
    shop_id: str
    date_from: str
    date_to: str
    sku_codes: list[str]
    domains: list[str]
    # 各 worker 写入，按 key 合并（不同 worker 写不同 key，无冲突）。
    results: Annotated[dict[str, Any], operator.or_]
    # 各节点追加的审计备注。
    notes: Annotated[list[str], operator.add]
    # 顶层错误（supervisor/synthesis 失败时写入）。
    error: dict
    # 仅由 synthesis 写入一次。
    diagnosis: dict


def _supervisor(state: DiagnosisState, config: RunnableConfig | None = None) -> list[Send]:
    """监督者（作为 START 条件边路由函数）：按 domains 动态派发到各领域智能体（并行）。"""
    domains = [d for d in (state.get('domains') or []) if d in DOMAIN_AGENTS]
    if not domains:
        domains = list(ALL_DOMAINS)
    sends = [Send(DOMAIN_AGENTS[d], state) for d in domains]
    return sends


def _make_worker(domain: str, tool_fn_name: str):
    def _node(state: DiagnosisState, config: RunnableConfig | None = None) -> dict:
        db = (config or {}).get('configurable', {}).get('db')
        user = (config or {}).get('configurable', {}).get('user')
        arguments = {
            'shop_id': state['shop_id'],
            'date_from': state['date_from'],
            'date_to': state['date_to'],
            'sku_codes': state.get('sku_codes') or [],
        }
        try:
            envelope = getattr(bet, tool_fn_name)(db, user, arguments)
        except Exception as exc:  # noqa: BLE001 - 证据采集异常必须被隔离，不能中断整图
            code = getattr(exc, 'code', None) or type(exc).__name__
            return {
                'results': {domain: {
                    'domain': domain, 'status': 'error', 'error_code': code,
                    'message': str(exc)[:500],
                }},
                'notes': [f'{domain} worker 异常: {code}'],
            }
        gaps = envelope.get('gaps') or []
        denied = any(g.get('code') == 'PERMISSION_REQUIRED' for g in gaps)
        payload = {
            'domain': domain,
            'status': 'denied' if denied else 'ok',
            'source': envelope.get('source'),
            'snapshot_at': envelope.get('snapshot_at'),
            'evidence_refs': envelope.get('evidence_refs') or [],
            'gaps': gaps,
            'findings': envelope.get('findings') or [],
            'summary': {
                k: v for k, v in envelope.items()
                if k not in ('evidence_refs', 'gaps', 'findings', 'source', 'source_version',
                             'rule_version', 'snapshot_at')
            },
        }
        return {
            'results': {domain: payload},
            'notes': [f'{domain} 采集完成（{payload["status"]}）'],
        }

    return _node


def _synthesis(state: DiagnosisState, config: RunnableConfig | None = None) -> dict:
    """合成节点：汇总所有领域智能体的证据，生成统一诊断结论。"""
    domains = [d for d in (state.get('domains') or ALL_DOMAINS) if d in DOMAIN_AGENTS]
    results = state.get('results') or {}

    evidence_refs: list[dict] = []
    gaps: list[dict] = []
    findings: list[dict] = []
    agents: list[dict] = []
    permission_gaps: list[dict] = []

    for domain in domains:
        payload = results.get(domain)
        if not payload:
            agents.append({
                'domain': domain, 'agent': DOMAIN_AGENTS.get(domain, domain),
                'status': 'skipped', 'ref_count': 0, 'gap_count': 0, 'finding_count': 0,
            })
            continue
        refs = payload.get('evidence_refs') or []
        d_gaps = payload.get('gaps') or []
        d_findings = payload.get('findings') or []
        evidence_refs.extend(refs)
        gaps.extend(d_gaps)
        findings.extend(d_findings)
        for g in d_gaps:
            if g.get('code') == 'PERMISSION_REQUIRED':
                permission_gaps.append({'domain': domain, 'permission': g.get('permission')})
        agents.append({
            'domain': domain,
            'agent': DOMAIN_AGENTS.get(domain, domain),
            'status': payload.get('status', 'ok'),
            'ref_count': len(refs),
            'gap_count': len(d_gaps),
            'finding_count': len(d_findings),
        })

    summary_lines = [
        f'联合诊断覆盖 {len(agents)} 个领域智能体，共采集 {len(evidence_refs)} 条证据引用。',
        f'发现 {len(findings)} 条交叉发现、{len(gaps)} 个数据缺口。',
    ]
    if permission_gaps:
        summary_lines.append('权限缺口：' + '；'.join(
            f'{p["domain"]} 需要 {p["permission"]}' for p in permission_gaps))
    if not any(a['status'] == 'ok' for a in agents):
        summary_lines.append('本账号当前权限下没有可读取的领域证据，请检查角色授权。')

    diagnosis = {
        'diagnosis_id': uuid.uuid4().hex,
        'shop_id': state['shop_id'],
        'period': {'date_from': state['date_from'], 'date_to': state['date_to']},
        'domains': domains,
        'agents': agents,
        'evidence_refs': evidence_refs,
        'gaps': gaps,
        'findings': findings,
        'permission_gaps': permission_gaps,
        'summary': '\n'.join(summary_lines),
        'supervisor_plan': [DOMAIN_AGENTS[d] for d in domains],
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }
    return {'diagnosis': diagnosis, 'notes': ['synthesis 完成汇总']}


def _build_graph() -> StateGraph:
    g = StateGraph(DiagnosisState)
    # 监督者以 START 条件边路由函数形式存在（见下方 add_conditional_edges），不单独注册为节点。
    for domain, agent in DOMAIN_AGENTS.items():
        g.add_node(agent, _make_worker(domain, DOMAIN_TOOL[domain]))
    g.add_node('synthesis', _synthesis)

    # 监督者作为入口路由：动态派发到各智能体（Send 对象，旁路 path_map）。
    g.add_conditional_edges(
        START, _supervisor,
        {**{agent: agent for agent in DOMAIN_AGENTS.values()}, 'synthesis': 'synthesis'},
    )
    # 所有领域智能体完成后汇入 synthesis（fan-in）。
    for agent in DOMAIN_AGENTS.values():
        g.add_edge(agent, 'synthesis')
    g.add_edge('synthesis', END)
    return g.compile()


# 模块加载时编译一次（图无状态，可复用）。
GRAPH = _build_graph()


def normalize_domains(domains: list[str] | None) -> list[str]:
    chosen = [d for d in (domains or []) if d in DOMAIN_AGENTS]
    return chosen or list(ALL_DOMAINS)


def run_diagnosis(db, user, params: dict) -> dict:
    """执行一次联合诊断，返回合成后的诊断结论（并写入内存存储）。

    params: { shop_id, date_from, date_to, sku_codes?, domains? }
    """
    shop_id = params['shop_id']
    date_from = params['date_from']
    date_to = params['date_to']
    sku_codes = params.get('sku_codes') or []
    domains = normalize_domains(params.get('domains'))

    state = GRAPH.invoke(
        {
            'shop_id': shop_id, 'date_from': date_from, 'date_to': date_to,
            'sku_codes': sku_codes, 'domains': domains,
            'results': {}, 'notes': [], 'error': {}, 'diagnosis': {},
        },
        {'configurable': {'db': db, 'user': user}},
    )
    diagnosis = state.get('diagnosis') or {}
    if not diagnosis.get('diagnosis_id'):
        # 极端情况：synthesis 未产出结论。
        diagnosis = {
            'diagnosis_id': uuid.uuid4().hex, 'shop_id': shop_id,
            'period': {'date_from': date_from, 'date_to': date_to},
            'domains': domains, 'agents': [], 'evidence_refs': [], 'gaps': [],
            'findings': [], 'permission_gaps': [],
            'summary': '诊断未产生结论（supervisor/synthesis 异常）。',
            'supervisor_plan': [], 'generated_at': datetime.now(timezone.utc).isoformat(),
        }
    DIAGNOSES[diagnosis['diagnosis_id']] = diagnosis
    if len(DIAGNOSES) > _MAX_MEMORY_RECORDS:
        for old_id in sorted(DIAGNOSES, key=lambda k: DIAGNOSES[k]['generated_at'])[:len(DIAGNOSES) - _MAX_MEMORY_RECORDS]:
            DIAGNOSES.pop(old_id, None)
    return diagnosis
