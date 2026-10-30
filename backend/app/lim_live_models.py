"""Durable state for the business-backed five-domain workbench."""
from datetime import datetime
from sqlalchemy import ForeignKey, JSON, String, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from . import models as m


class LiveRun(m.Record, m.Base):
    __tablename__ = 'lim_live_runs'
    workflow_run_id: Mapped[str] = mapped_column(ForeignKey('lim_workflow_runs.workflow_run_id'), unique=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id'))
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id'))
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(nullable=True)
    child_run_ids: Mapped[list] = mapped_column(JSON, default=list)


class LiveCheckpoint(m.Record, m.Base):
    __tablename__ = 'lim_live_checkpoints'
    __table_args__ = (UniqueConstraint('run_id', 'version', name='uq_live_checkpoint_version'),)
    run_id: Mapped[str] = mapped_column(ForeignKey('lim_live_runs.id'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    node_id: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))


class LiveMemory(m.Record, m.Base):
    __tablename__ = 'lim_live_memories'
    __table_args__ = (UniqueConstraint('run_id', 'node_id', 'tier', name='uq_live_memory_source'),)
    run_id: Mapped[str] = mapped_column(ForeignKey('lim_live_runs.id'), index=True)
    node_id: Mapped[str] = mapped_column(String(32))
    tier: Mapped[str] = mapped_column(String(16))
    content: Mapped[dict] = mapped_column(JSON)
    archived: Mapped[bool] = mapped_column(default=False)


class LiveEvaluation(m.Record, m.Base):
    __tablename__ = 'lim_live_evaluations'
    __table_args__ = (UniqueConstraint('run_id', name='uq_lim_live_evaluations_run_id'),)
    run_id: Mapped[str] = mapped_column(ForeignKey('lim_live_runs.id'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict] = mapped_column(JSON)
    usage: Mapped[dict] = mapped_column(JSON)
    delivery: Mapped[dict] = mapped_column(JSON, default=dict)
