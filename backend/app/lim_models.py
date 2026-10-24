from datetime import datetime

from sqlalchemy import (
    CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON,
    Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from . import models as m


RUN_STATUSES = (
    'CREATED', 'SCOPE_CHECKED', 'PLANNED', 'RUNNING', 'VERIFYING', 'COMPLETED',
    'REVIEW_REQUIRED', 'APPROVED', 'EXECUTING', 'RECONCILING', 'REJECTED',
    'FAILED', 'WAITING_INPUT', 'WAITING_RECONCILIATION', 'BUDGET_EXCEEDED', 'CANCELLED',
)


class LimAgent(m.Record, m.Base):
    __tablename__ = 'lim_agents'
    __table_args__ = (
        UniqueConstraint('agent_id', 'version', name='uq_lim_agents_agent_version'),
        CheckConstraint("status IN ('draft', 'validated', 'archived')", name='ck_lim_agents_status'),
        Index('ix_lim_agents_status_agent', 'status', 'agent_id'),
    )

    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(120))
    business_domain: Mapped[str] = mapped_column(String(64), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    definition: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default='draft')


class LimTool(m.Record, m.Base):
    __tablename__ = 'lim_tools'
    __table_args__ = (
        UniqueConstraint('tool_id', 'version', name='uq_lim_tools_tool_version'),
        CheckConstraint("operation_kind IN ('read', 'write')", name='ck_lim_tools_operation_kind'),
        CheckConstraint("risk_tier IN ('low', 'medium', 'high', 'critical')", name='ck_lim_tools_risk_tier'),
        CheckConstraint("status IN ('draft', 'active', 'archived')", name='ck_lim_tools_status'),
        CheckConstraint('timeout_ms > 0', name='ck_lim_tools_timeout_positive'),
        Index('ix_lim_tools_status_domain', 'status', 'domain'),
    )

    tool_id: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[str] = mapped_column(String(32))
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    service: Mapped[str] = mapped_column(String(80))
    domain: Mapped[str] = mapped_column(String(64), index=True)
    operation_kind: Mapped[str] = mapped_column(String(8))
    risk_tier: Mapped[str] = mapped_column(String(16))
    timeout_ms: Mapped[int] = mapped_column(Integer)
    rate_limit: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    idempotency_mode: Mapped[str] = mapped_column(String(32))
    scope_policy: Mapped[dict] = mapped_column(JSON)
    input_schema: Mapped[dict] = mapped_column(JSON)
    output_schema: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default='draft')


class LimRun(m.Record, m.Base):
    __tablename__ = 'lim_runs'
    __table_args__ = (
        UniqueConstraint('run_id', name='uq_lim_runs_run_id'),
        ForeignKeyConstraint(['agent_id', 'agent_version'], ['lim_agents.agent_id', 'lim_agents.version'],
                             ondelete='RESTRICT', name='fk_lim_runs_agent_version'),
        CheckConstraint(
            "status IN ('CREATED','SCOPE_CHECKED','PLANNED','RUNNING','VERIFYING','COMPLETED',"
            "'REVIEW_REQUIRED','APPROVED','EXECUTING','RECONCILING','REJECTED','FAILED',"
            "'WAITING_INPUT','WAITING_RECONCILIATION','BUDGET_EXCEEDED','CANCELLED')",
            name='ck_lim_runs_status',
        ),
        Index('ix_lim_runs_status_created', 'status', 'created_at'),
        Index('ix_lim_runs_actor_created', 'actor_id', 'created_at'),
        Index('ix_lim_runs_trace_id', 'trace_id'),
    )

    run_id: Mapped[str] = mapped_column(String(36))
    execution_mode: Mapped[str] = mapped_column(String(16), default='live', server_default='live')
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    scope_ref: Mapped[str] = mapped_column(String(36), index=True)
    scope_snapshot: Mapped[dict] = mapped_column(JSON)
    agent_id: Mapped[str] = mapped_column(String(64))
    agent_version: Mapped[str] = mapped_column(String(32))
    trace_id: Mapped[str] = mapped_column(String(36))
    goal_summary: Mapped[str] = mapped_column(Text)
    input_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    output_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    budget: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default='CREATED')
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    token_usage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class LimSpan(m.Record, m.Base):
    __tablename__ = 'lim_spans'
    __table_args__ = (
        UniqueConstraint('span_id', name='uq_lim_spans_span_id'),
        CheckConstraint("status IN ('RUNNING','SUCCEEDED','FAILED','REJECTED','CANCELLED')", name='ck_lim_spans_status'),
        Index('ix_lim_spans_run_started', 'run_id', 'created_at'),
    )

    run_id: Mapped[str] = mapped_column(ForeignKey('lim_runs.run_id', ondelete='CASCADE'), index=True)
    span_id: Mapped[str] = mapped_column(String(36))
    parent_span_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), default='RUNNING')
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_usage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)


class LimToolInvocation(m.Record, m.Base):
    __tablename__ = 'lim_tool_invocations'
    __table_args__ = (
        UniqueConstraint('invocation_id', name='uq_lim_tool_invocations_id'),
        ForeignKeyConstraint(['tool_id', 'tool_version'], ['lim_tools.tool_id', 'lim_tools.version'],
                             ondelete='RESTRICT', name='fk_lim_invocations_tool_version'),
        CheckConstraint("status IN ('PENDING','SUCCEEDED','FAILED','BLOCKED','TIMEOUT')", name='ck_lim_invocations_status'),
        Index('ix_lim_invocations_run_created', 'run_id', 'created_at'),
    )

    invocation_id: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(ForeignKey('lim_runs.run_id', ondelete='CASCADE'), index=True)
    span_id: Mapped[str] = mapped_column(ForeignKey('lim_spans.span_id', ondelete='RESTRICT'), index=True)
    tool_id: Mapped[str] = mapped_column(String(120))
    tool_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default='PENDING')
    read_only: Mapped[bool] = mapped_column(default=True)
    arguments_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    response_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class LimEvalDataset(m.Record, m.Base):
    __tablename__ = 'lim_eval_datasets'
    __table_args__ = (
        UniqueConstraint('dataset_id', 'version', name='uq_lim_eval_datasets_version'),
        CheckConstraint("status IN ('draft','frozen','archived')", name='ck_lim_eval_datasets_status'),
    )

    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(1000), default='')
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    status: Mapped[str] = mapped_column(String(16), default='draft')


class LimEvalCase(m.Record, m.Base):
    __tablename__ = 'lim_eval_cases'
    __table_args__ = (
        ForeignKeyConstraint(['dataset_id', 'dataset_version'], ['lim_eval_datasets.dataset_id', 'lim_eval_datasets.version'],
                             ondelete='RESTRICT', name='fk_lim_eval_cases_dataset_version'),
        UniqueConstraint('dataset_id', 'dataset_version', 'case_id', name='uq_lim_eval_cases_key'),
        CheckConstraint("risk_tier IN ('low','medium','high','critical')", name='ck_lim_eval_cases_risk'),
        Index('ix_lim_eval_cases_dataset_version', 'dataset_id', 'dataset_version'),
    )

    dataset_id: Mapped[str] = mapped_column(String(64))
    dataset_version: Mapped[str] = mapped_column(String(32))
    case_id: Mapped[str] = mapped_column(String(64))
    scenario: Mapped[str] = mapped_column(String(500))
    input_payload: Mapped[dict] = mapped_column(JSON)
    scope: Mapped[dict] = mapped_column(JSON)
    ground_truth: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    acceptable_outputs: Mapped[list] = mapped_column(JSON, default=list)
    required_evidence: Mapped[list] = mapped_column(JSON, default=list)
    forbidden_actions: Mapped[list] = mapped_column(JSON, default=list)
    risk_tier: Mapped[str] = mapped_column(String(16))
    tags: Mapped[list] = mapped_column(JSON, default=list)


class LimEvalRun(m.Record, m.Base):
    __tablename__ = 'lim_eval_runs'
    __table_args__ = (
        ForeignKeyConstraint(['dataset_id', 'dataset_version'], ['lim_eval_datasets.dataset_id', 'lim_eval_datasets.version'],
                             ondelete='RESTRICT', name='fk_lim_eval_runs_dataset_version'),
        ForeignKeyConstraint(['agent_id', 'agent_version'], ['lim_agents.agent_id', 'lim_agents.version'],
                             ondelete='RESTRICT', name='fk_lim_eval_runs_agent_version'),
        CheckConstraint("status IN ('QUEUED','RUNNING','COMPLETED','FAILED')", name='ck_lim_eval_runs_status'),
        Index('ix_lim_eval_runs_status_created', 'status', 'created_at'),
    )

    eval_run_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    dataset_id: Mapped[str] = mapped_column(String(64))
    dataset_version: Mapped[str] = mapped_column(String(32))
    agent_id: Mapped[str] = mapped_column(String(64))
    agent_version: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    environment: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), default='QUEUED')
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class LimEvalCaseResult(m.Record, m.Base):
    __tablename__ = 'lim_eval_case_results'
    __table_args__ = (
        UniqueConstraint('eval_run_id', 'case_id', name='uq_lim_eval_case_results_case'),
        ForeignKeyConstraint(['dataset_id', 'dataset_version', 'case_id'],
                             ['lim_eval_cases.dataset_id', 'lim_eval_cases.dataset_version', 'lim_eval_cases.case_id'],
                             ondelete='RESTRICT', name='fk_lim_eval_results_case'),
        CheckConstraint("outcome IN ('PASS','FAIL','NOT_EVALUATED')", name='ck_lim_eval_case_results_outcome'),
        Index('ix_lim_eval_case_results_run', 'eval_run_id'),
    )

    eval_run_id: Mapped[str] = mapped_column(ForeignKey('lim_eval_runs.eval_run_id', ondelete='CASCADE'))
    dataset_id: Mapped[str] = mapped_column(String(64))
    dataset_version: Mapped[str] = mapped_column(String(32))
    case_id: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16))
    actual_output: Mapped[dict] = mapped_column(JSON, default=dict)
    failures: Mapped[list] = mapped_column(JSON, default=list)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class LimEvalComparison(m.Record, m.Base):
    __tablename__ = 'lim_eval_comparisons'
    __table_args__ = (
        UniqueConstraint('comparison_id', name='uq_lim_eval_comparisons_id'),
        CheckConstraint("status IN ('PASS','FAIL','NOT_EVALUATED')", name='ck_lim_eval_comparisons_status'),
        Index('ix_lim_eval_comparisons_actor_created', 'actor_id', 'created_at'),
    )

    comparison_id: Mapped[str] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    baseline_eval_run_id: Mapped[str] = mapped_column(ForeignKey('lim_eval_runs.eval_run_id', ondelete='RESTRICT'))
    candidate_eval_run_id: Mapped[str] = mapped_column(ForeignKey('lim_eval_runs.eval_run_id', ondelete='RESTRICT'))
    report: Mapped[dict] = mapped_column(JSON)
    report_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))


class LimKnowledgeSource(m.Record, m.Base):
    __tablename__ = 'lim_knowledge_sources'
    __table_args__ = (
        UniqueConstraint('source_id', name='uq_lim_knowledge_sources_source_id'),
        UniqueConstraint('path', name='uq_lim_knowledge_sources_path'),
        CheckConstraint('length(trim(display_name)) > 0', name='ck_lim_knowledge_sources_name_nonempty'),
        Index('ix_lim_knowledge_sources_archived_present', 'is_archived', 'is_present'),
    )

    source_id: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(String(500))
    display_name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(64), default='general')
    summary: Mapped[str] = mapped_column(Text, default='')
    required_permissions: Mapped[list] = mapped_column(JSON, default=list)
    is_present: Mapped[bool] = mapped_column(default=True)
    is_archived: Mapped[bool] = mapped_column(default=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)


class LimKnowledgeSourceVersion(m.Record, m.Base):
    __tablename__ = 'lim_knowledge_source_versions'
    __table_args__ = (
        UniqueConstraint('source_id', 'version', name='uq_lim_knowledge_source_versions_version'),
        ForeignKeyConstraint(['source_id'], ['lim_knowledge_sources.source_id'], ondelete='RESTRICT',
                             name='fk_lim_knowledge_source_versions_source'),
        CheckConstraint("status IN ('draft','active','archived')", name='ck_lim_knowledge_source_versions_status'),
        CheckConstraint('valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from',
                        name='ck_lim_knowledge_source_versions_validity'),
        Index('ix_lim_knowledge_source_versions_status', 'status', 'created_at'),
        Index('uq_lim_knowledge_source_versions_one_active', 'source_id', unique=True,
              sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'")),
    )

    source_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default='draft')
    valid_from: Mapped[datetime | None] = mapped_column(nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class LimKnowledgeChunk(m.Record, m.Base):
    __tablename__ = 'lim_knowledge_chunks'
    __table_args__ = (
        UniqueConstraint('source_id', 'version', 'chunk_id', name='uq_lim_knowledge_chunks_identity'),
        ForeignKeyConstraint(['source_id', 'version'],
                             ['lim_knowledge_source_versions.source_id', 'lim_knowledge_source_versions.version'],
                             ondelete='RESTRICT', name='fk_lim_knowledge_chunks_version'),
        CheckConstraint('start_line > 0 AND end_line >= start_line', name='ck_lim_knowledge_chunks_lines'),
        Index('ix_lim_knowledge_chunks_source_version', 'source_id', 'version'),
    )

    source_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(64))
    chunk_id: Mapped[str] = mapped_column(String(64))
    section: Mapped[str] = mapped_column(String(200))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))


class LimWorkflow(m.Record, m.Base):
    __tablename__ = 'lim_workflows'
    __table_args__ = (
        UniqueConstraint('workflow_id', name='uq_lim_workflows_workflow_id'),
        CheckConstraint("status IN ('draft','active','archived')", name='ck_lim_workflows_status'),
        Index('ix_lim_workflows_domain_status', 'business_domain', 'status'),
    )

    workflow_id: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(120))
    business_domain: Mapped[str] = mapped_column(String(64))
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    status: Mapped[str] = mapped_column(String(16), default='draft')


class LimWorkflowVersion(m.Record, m.Base):
    __tablename__ = 'lim_workflow_versions'
    __table_args__ = (
        UniqueConstraint('workflow_id', 'version', name='uq_lim_workflow_versions_version'),
        ForeignKeyConstraint(['workflow_id'], ['lim_workflows.workflow_id'], ondelete='RESTRICT',
                             name='fk_lim_workflow_versions_workflow'),
        CheckConstraint("status IN ('draft','validated','archived')", name='ck_lim_workflow_versions_status'),
        Index('ix_lim_workflow_versions_status', 'status', 'created_at'),
    )

    workflow_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    definition: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default='draft')
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    validated_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(nullable=True)


class LimWorkflowRun(m.Record, m.Base):
    __tablename__ = 'lim_workflow_runs'
    __table_args__ = (
        UniqueConstraint('workflow_run_id', name='uq_lim_workflow_runs_run_id'),
        ForeignKeyConstraint(['workflow_id', 'workflow_version'],
                             ['lim_workflow_versions.workflow_id', 'lim_workflow_versions.version'],
                             ondelete='RESTRICT', name='fk_lim_workflow_runs_version'),
        CheckConstraint("status IN ('CREATED','RUNNING','COMPLETED','COMPLETED_WITH_CONFLICTS','PARTIAL','FAILED','CANCELLED','BUDGET_EXCEEDED')",
                        name='ck_lim_workflow_runs_status'),
        Index('ix_lim_workflow_runs_actor_created', 'actor_id', 'created_at'),
        Index('ix_lim_workflow_runs_status_created', 'status', 'created_at'),
    )

    workflow_run_id: Mapped[str] = mapped_column(String(36))
    workflow_id: Mapped[str] = mapped_column(String(64))
    workflow_version: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    scope_ref: Mapped[str] = mapped_column(String(36), index=True)
    scope_snapshot: Mapped[dict] = mapped_column(JSON)
    input_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    output_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    budget: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default='CREATED')
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    cancellation_requested: Mapped[bool] = mapped_column(default=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class LimWorkflowTask(m.Record, m.Base):
    __tablename__ = 'lim_workflow_tasks'
    __table_args__ = (
        UniqueConstraint('workflow_run_id', 'node_id', name='uq_lim_workflow_tasks_node'),
        ForeignKeyConstraint(['workflow_run_id'], ['lim_workflow_runs.workflow_run_id'], ondelete='RESTRICT',
                             name='fk_lim_workflow_tasks_run'),
        ForeignKeyConstraint(['child_run_id'], ['lim_runs.run_id'], ondelete='RESTRICT',
                             name='fk_lim_workflow_tasks_child_run'),
        CheckConstraint("status IN ('PENDING','RUNNING','COMPLETED','SKIPPED','FAILED','CANCELLED','BUDGET_EXCEEDED')",
                        name='ck_lim_workflow_tasks_status'),
        Index('ix_lim_workflow_tasks_status', 'workflow_run_id', 'status'),
    )

    workflow_run_id: Mapped[str] = mapped_column(String(36))
    node_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default='PENDING')
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    child_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    result_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    condition_result: Mapped[bool | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class LimSkill(m.Record, m.Base):
    __tablename__ = 'lim_skills'
    __table_args__ = (
        UniqueConstraint('skill_id', name='uq_lim_skills_skill_id'),
        Index('ix_lim_skills_owner_name', 'owner_id', 'display_name'),
    )

    skill_id: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)


class LimSkillVersion(m.Record, m.Base):
    __tablename__ = 'lim_skill_versions'
    __table_args__ = (
        UniqueConstraint('skill_id', 'version', name='uq_lim_skill_versions_version'),
        ForeignKeyConstraint(['skill_id'], ['lim_skills.skill_id'], ondelete='RESTRICT',
                             name='fk_lim_skill_versions_skill'),
        CheckConstraint("status IN ('CANDIDATE','UNDER_REVIEW','VERIFIED','ACTIVE','DEGRADED','FROZEN','REVOKED')",
                        name='ck_lim_skill_versions_status'),
        CheckConstraint("memory_level IN ('short_term','episodic','semantic','procedural')",
                        name='ck_lim_skill_versions_memory_level'),
        CheckConstraint('usage_count >= 0 AND correction_count >= 0',
                        name='ck_lim_skill_versions_counts_nonnegative'),
        Index('ix_lim_skill_versions_state', 'status', 'updated_at'),
        Index('uq_lim_skill_versions_one_active', 'skill_id', unique=True,
              postgresql_where=text("status = 'ACTIVE'"), sqlite_where=text("status = 'ACTIVE'")),
    )

    skill_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    memory_level: Mapped[str] = mapped_column(String(16))
    definition: Mapped[dict] = mapped_column(JSON)
    source_event: Mapped[str] = mapped_column(String(200))
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    business_scope: Mapped[dict] = mapped_column(JSON)
    last_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    confidence_calibration: Mapped[dict] = mapped_column(JSON, default=dict)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    correction_count: Mapped[int] = mapped_column(Integer, default=0)
    expiry_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default='CANDIDATE')
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=True)
    activated_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=True)
    transitioned_at: Mapped[datetime | None] = mapped_column(nullable=True)




class LimAlertRule(m.Record, m.Base):
    __tablename__ = 'lim_alert_rules'
    __table_args__ = (
        UniqueConstraint('rule_key', name='uq_lim_alert_rules_key'),
        CheckConstraint("dimension IN ('agent','tool','workflow')", name='ck_lim_alert_rules_dimension'),
        CheckConstraint('threshold BETWEEN 1 AND 1000', name='ck_lim_alert_rules_threshold'),
        CheckConstraint('window_seconds BETWEEN 60 AND 86400', name='ck_lim_alert_rules_window'),
        Index('ix_lim_alert_rules_enabled', 'enabled'),
    )

    rule_key: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(120))
    dimension: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(default=True, server_default=text('1'))
    threshold: Mapped[int] = mapped_column(Integer)
    window_seconds: Mapped[int] = mapped_column(Integer)


class LimAlert(m.Record, m.Base):
    __tablename__ = 'lim_alerts'
    __table_args__ = (
        UniqueConstraint('dedupe_key', name='uq_lim_alerts_dedupe_key'),
        CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','CLOSED')", name='ck_lim_alerts_status'),
        Index('ix_lim_alerts_status_last_seen', 'status', 'last_seen_at'),
        Index('ix_lim_alerts_actor_created', 'actor_id', 'created_at'),
        Index('ix_lim_alerts_entity', 'rule_key', 'entity_key'),
    )

    alert_id: Mapped[str] = mapped_column(String(36), unique=True)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    rule_key: Mapped[str] = mapped_column(ForeignKey('lim_alert_rules.rule_key', ondelete='RESTRICT'), index=True)
    entity_key: Mapped[str] = mapped_column(String(120))
    entity_label: Mapped[str] = mapped_column(String(160))
    severity: Mapped[str] = mapped_column(String(16), default='warning')
    status: Mapped[str] = mapped_column(String(16), default='OPEN')
    summary: Mapped[str] = mapped_column(String(240))
    error_code: Mapped[str] = mapped_column(String(64))
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tool_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    acknowledged_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(nullable=True)
    closed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)


MODEL_CALL_STATUSES = ('SUCCEEDED', 'FAILED', 'CACHED', 'REJECTED')


class LimModelProvider(m.Record, m.Base):
    """已注册的模型供应商。api_key_env 只保存环境变量名，明文 key 绝不落库。"""
    __tablename__ = 'lim_model_providers'
    __table_args__ = (
        UniqueConstraint('provider_id', name='uq_lim_model_providers_id'),
        CheckConstraint("protocol IN ('openai_compatible')", name='ck_lim_model_providers_protocol'),
        CheckConstraint("status IN ('ACTIVE','DISABLED','UNHEALTHY')", name='ck_lim_model_providers_status'),
        Index('ix_lim_model_providers_status', 'status'),
    )

    provider_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    protocol: Mapped[str] = mapped_column(String(32), default='openai_compatible')
    base_url: Mapped[str] = mapped_column(String(500))
    api_key_env: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(default=True, server_default=text('true'))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=40000)
    status: Mapped[str] = mapped_column(String(16), default='ACTIVE')


class LimModelCatalog(m.Record, m.Base):
    """逻辑模型别名 → 实际供应商 + 模型名，支持按场景（scene）分流。"""
    __tablename__ = 'lim_model_catalog'
    __table_args__ = (
        UniqueConstraint('alias_id', name='uq_lim_model_catalog_id'),
        ForeignKeyConstraint(['provider_id'], ['lim_model_providers.provider_id'], ondelete='RESTRICT',
                             name='fk_lim_model_catalog_provider'),
        Index('ix_lim_model_catalog_alias_scene', 'alias', 'scene'),
    )

    alias_id: Mapped[str] = mapped_column(String(36))
    alias: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(128))
    scene: Mapped[str] = mapped_column(String(64), default='*')
    enabled: Mapped[bool] = mapped_column(default=True, server_default=text('true'))
    priority: Mapped[int] = mapped_column(Integer, default=100)


class LimModelCall(m.Record, m.Base):
    """单次模型调用的观测记录 —— 点亮 lim_metrics 的 token_usage / cost / cache_hit。"""
    __tablename__ = 'lim_model_calls'
    __table_args__ = (
        UniqueConstraint('call_id', name='uq_lim_model_calls_id'),
        CheckConstraint("status IN ('SUCCEEDED','FAILED','CACHED','REJECTED')", name='ck_lim_model_calls_status'),
        ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='RESTRICT', name='fk_lim_model_calls_actor'),
        Index('ix_lim_model_calls_created_at', 'created_at'),
        Index('ix_lim_model_calls_actor_created', 'actor_id', 'created_at'),
        Index('ix_lim_model_calls_provider_created', 'provider_id', 'created_at'),
        Index('ix_lim_model_calls_run_id', 'run_id'),
        Index('ix_lim_model_calls_request_hash', 'request_hash'),
    )

    call_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    span_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    alias: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 无单价表时保持 NULL，不填 0 假装准确。
    cost: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    cache_hit: Mapped[bool] = mapped_column(default=False, server_default=text('false'))
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
