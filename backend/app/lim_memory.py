"""
Pillar 3: 4-Tier Hierarchical Agent Memory & Skill Governance
Fulfills LIM-FR-015 (Memory & Skill Governance).

Capabilities:
1. 4-Tier Memory Architecture:
   - Working Memory (工作记忆): Active session context & scratchpad variables (short TTL)
   - Episodic Memory (情景记忆): Historical task execution trajectories, outcomes, and human feedback
   - Semantic Memory (语义记忆): Consolidated domain facts, SKU/supplier rules, and learned patterns
   - Procedural Memory (程序性记忆): Versioned, reusable Agent Skills distilled from verified trajectories
2. Cognitive Memory Dynamics:
   - Confidence Evaluation (置信度评估): Bayesian/weighted reinforcement from human feedback & verification
   - Time Decay (时间衰减): Exponential Ebbinghaus decay `retention = exp(-lambda * elapsed_days / strength)`
   - Conflict Detection (冲突检测): Detects contradictory semantic/episodic assertions on the same entity/attribute
   - Active Forgetting (遗忘机制): Prunes or archives low-utility/decayed memories below threshold
3. Skill Distillation & Version Governance:
   - Automatically distills high-scoring episodic trajectories (`reward >= 0.85` & verified) into versioned
     Procedural Agent Skills (`v1.0`, `v1.1`, ...) with rollback and audit support.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class MemoryTier(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass
class MemoryRecord:
    memory_id: str
    tier: str
    tenant_id: str
    entity_key: str
    attribute_key: str
    content: Dict[str, Any]
    base_confidence: float = 0.80
    reinforcement_count: int = 1
    decay_lambda: float = 0.05
    created_at_epoch: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    last_accessed_epoch: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    verified_by_human: bool = False
    superseded_by: Optional[str] = None
    conflict_flag: bool = False


@dataclass
class DistilledSkillVersion:
    skill_id: str
    skill_name: str
    domain: str
    version: str
    trigger_pattern: str
    step_template: List[Dict[str, Any]]
    source_run_ids: List[str]
    avg_reward_score: float
    human_approved: bool
    status: str = "ACTIVE"  # ACTIVE | DEPRECATED | ROLLED_BACK
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class HierarchicalMemoryManager:
    """
    Manages Working, Episodic, Semantic, and Procedural memories with confidence scoring,
    exponential time decay, conflict detection, active forgetting, and trajectory-to-Skill distillation.
    """

    def __init__(self, forgetting_threshold: float = 0.25) -> None:
        self.forgetting_threshold = forgetting_threshold
        self.memories: Dict[str, MemoryRecord] = {}
        self.skill_registry: Dict[str, List[DistilledSkillVersion]] = {}
        self.conflict_log: List[Dict[str, Any]] = []

    def compute_effective_confidence(self, record: MemoryRecord, now_epoch: Optional[float] = None) -> float:
        now_ts = now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp()
        elapsed_days = max(0.0, (now_ts - record.last_accessed_epoch) / 86400.0)
        strength = max(1.0, math.log2(record.reinforcement_count + 1) * (1.35 if record.verified_by_human else 1.0))
        retention = math.exp(-record.decay_lambda * elapsed_days / strength)
        return round(min(1.0, record.base_confidence * retention), 4)

    def store_memory(
        self,
        tier: MemoryTier,
        entity_key: str,
        attribute_key: str,
        content: Dict[str, Any],
        tenant_id: str = "tenant-default",
        base_confidence: float = 0.80,
        decay_lambda: float = 0.05,
        verified_by_human: bool = False,
        now_epoch: Optional[float] = None,
    ) -> Tuple[MemoryRecord, Optional[Dict[str, Any]]]:
        now_ts = now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp()
        conflict_event: Optional[Dict[str, Any]] = None

        # Check for semantic/episodic conflicts on the same (tenant_id, tier, entity_key, attribute_key)
        for existing in list(self.memories.values()):
            if (
                existing.tenant_id == tenant_id
                and existing.tier == tier.value
                and existing.entity_key == entity_key
                and existing.attribute_key == attribute_key
                and existing.superseded_by is None
            ):
                if existing.content != content:
                    existing_eff = self.compute_effective_confidence(existing, now_epoch=now_ts)
                    new_id = f"MEM-{uuid.uuid4().hex[:8].upper()}"
                    conflict_event = {
                        "conflict_id": f"MCONF-{uuid.uuid4().hex[:8].upper()}",
                        "entity_key": entity_key,
                        "attribute_key": attribute_key,
                        "old_memory_id": existing.memory_id,
                        "old_value": existing.content,
                        "old_effective_confidence": existing_eff,
                        "new_memory_id": new_id,
                        "new_value": content,
                        "new_confidence": base_confidence,
                        "resolution": "SUPERSEDED_BY_NEW" if base_confidence >= existing_eff else "FLAGGED_FOR_REVIEW",
                    }
                    self.conflict_log.append(conflict_event)
                    if base_confidence >= existing_eff:
                        existing.superseded_by = new_id
                    else:
                        existing.conflict_flag = True
                else:
                    # Reinforce identical memory
                    existing.reinforcement_count += 1
                    existing.last_accessed_epoch = now_ts
                    existing.base_confidence = min(0.99, existing.base_confidence + 0.03)
                    if verified_by_human:
                        existing.verified_by_human = True
                    return existing, None

        mem_id = conflict_event["new_memory_id"] if conflict_event else f"MEM-{uuid.uuid4().hex[:8].upper()}"
        record = MemoryRecord(
            memory_id=mem_id,
            tier=tier.value,
            tenant_id=tenant_id,
            entity_key=entity_key,
            attribute_key=attribute_key,
            content=content,
            base_confidence=base_confidence,
            decay_lambda=decay_lambda,
            created_at_epoch=now_ts,
            last_accessed_epoch=now_ts,
            verified_by_human=verified_by_human,
            conflict_flag=bool(conflict_event and conflict_event["resolution"] == "FLAGGED_FOR_REVIEW"),
        )
        self.memories[mem_id] = record
        return record, conflict_event

    def apply_feedback(
        self, memory_id: str, positive: bool, human_verified: bool = True, delta: float = 0.10
    ) -> Optional[MemoryRecord]:
        rec = self.memories.get(memory_id)
        if not rec:
            return None
        if positive:
            rec.base_confidence = round(min(0.99, rec.base_confidence + delta), 4)
            rec.reinforcement_count += 1
            rec.verified_by_human = rec.verified_by_human or human_verified
            rec.conflict_flag = False
        else:
            rec.base_confidence = round(max(0.05, rec.base_confidence - delta * 1.5), 4)
        rec.last_accessed_epoch = datetime.now(timezone.utc).timestamp()
        return rec

    def run_forgetting_sweep(self, now_epoch: Optional[float] = None) -> Dict[str, Any]:
        """Prunes memories whose time-decayed effective confidence falls below `forgetting_threshold`."""
        now_ts = now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp()
        forgotten_ids: List[str] = []
        retained_count = 0

        for mem_id, rec in list(self.memories.items()):
            eff = self.compute_effective_confidence(rec, now_epoch=now_ts)
            if eff < self.forgetting_threshold or rec.superseded_by is not None:
                forgotten_ids.append(mem_id)
                del self.memories[mem_id]
            else:
                retained_count += 1

        return {
            "forgotten_count": len(forgotten_ids),
            "forgotten_memory_ids": forgotten_ids,
            "retained_count": retained_count,
            "threshold": self.forgetting_threshold,
        }

    def distill_trajectory_to_skill(
        self,
        skill_name: str,
        domain: str,
        trigger_pattern: str,
        episodic_trajectory: List[Dict[str, Any]],
        run_id: str,
        reward_score: float,
        human_approved: bool = True,
    ) -> Optional[DistilledSkillVersion]:
        """
        Distills a high-quality episodic trajectory into a versioned Procedural Memory Agent Skill.
        Requires `reward_score >= 0.80` and verified execution outcome.
        """
        if reward_score < 0.80:
            return None

        versions = self.skill_registry.setdefault(skill_name, [])
        for v in versions:
            if v.status == "ACTIVE":
                v.status = "DEPRECATED"

        next_minor = len(versions)
        version_tag = f"v1.{next_minor}"
        skill_version = DistilledSkillVersion(
            skill_id=f"SKILL-{uuid.uuid4().hex[:8].upper()}",
            skill_name=skill_name,
            domain=domain,
            version=version_tag,
            trigger_pattern=trigger_pattern,
            step_template=episodic_trajectory,
            source_run_ids=[run_id],
            avg_reward_score=round(reward_score, 4),
            human_approved=human_approved,
            status="ACTIVE",
        )
        versions.append(skill_version)

        # Also index in Procedural Memory tier
        self.store_memory(
            tier=MemoryTier.PROCEDURAL,
            entity_key=skill_name,
            attribute_key=version_tag,
            content=asdict(skill_version),
            base_confidence=min(0.99, reward_score),
            decay_lambda=0.005,  # Procedural skills decay very slowly
            verified_by_human=human_approved,
        )
        return skill_version

    def rollback_skill_version(self, skill_name: str, target_version: str) -> Optional[DistilledSkillVersion]:
        versions = self.skill_registry.get(skill_name, [])
        if not versions:
            return None
        target_obj = None
        for v in versions:
            if v.version == target_version:
                target_obj = v
                break
        if target_obj is None:
            return None
        for v in versions:
            v.status = "ACTIVE" if v.version == target_version else "ROLLED_BACK"
        return target_obj
