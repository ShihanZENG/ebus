"""Application-owned risk and strategy objects; ERP owns business facts."""
from datetime import date, datetime
from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from . import models as m


class RiskEvent(m.Record, m.Base):
    __tablename__ = 'decision_risks'
    profile_id: Mapped[str] = mapped_column(ForeignKey('purchase_agent_profiles.id'), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True)
    business_date: Mapped[date]
    risk_type: Mapped[str] = mapped_column(String(40), default='STOCKOUT')
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default='OPEN')
    detected_at: Mapped[datetime] = mapped_column(default=m.now)
    metrics: Mapped[dict] = mapped_column(JSON)
    source: Mapped[dict] = mapped_column(JSON)
    history: Mapped[list] = mapped_column(JSON, default=list)


class StrategyTask(m.Record, m.Base):
    __tablename__ = 'decision_tasks'
    risk_id: Mapped[str] = mapped_column(ForeignKey('decision_risks.id'), index=True)
    objective: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(24), default='DRAFT')
    selected_version: Mapped[str | None] = mapped_column(String(36), nullable=True)
    selected_scenario: Mapped[int | None] = mapped_column(nullable=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    execution: Mapped[dict] = mapped_column(JSON, default=dict)
    execution_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    history: Mapped[list] = mapped_column(JSON, default=list)


class StrategyVersion(m.Record, m.Base):
    __tablename__ = 'decision_versions'
    __table_args__ = (UniqueConstraint('task_id', 'version', name='uq_decision_task_version'),)
    task_id: Mapped[str] = mapped_column(ForeignKey('decision_tasks.id'), index=True)
    version: Mapped[int]
    evidence_hash: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    scenarios: Mapped[list] = mapped_column(JSON)
    calculation_version: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[datetime]
