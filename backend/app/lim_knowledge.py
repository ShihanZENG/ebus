"""Versioned, ACL-aware catalog for approved local Markdown knowledge."""

import hashlib
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import or_, select, update

from . import models as m
from .assistant_knowledge import _HEADING_RE, _read_chunks, _tokens
from .lim_errors import LimRuntimeError
from .lim_models import LimKnowledgeChunk, LimKnowledgeSource, LimKnowledgeSourceVersion
from .security import record_audit, role_for


_ROOT = Path(__file__).resolve().parents[2]
_ALLOWED_DOC_DIRS = ('docs/功能章节', 'docs/oms')
_H1_RE = re.compile(r'^#\s+(.+?)\s*#*\s*$')


def _safe_files(repo_root: Path):
    root = repo_root.resolve()
    rejected = 0
    for directory in _ALLOWED_DOC_DIRS:
        base = repo_root / directory
        if not base.exists():
            continue
        components = [repo_root / 'docs', base]
        current = repo_root
        for part in Path(directory).parts:
            current = current / part
            components.append(current)
        if any(component.is_symlink() for component in components):
            rejected += 1
            continue
        try:
            safe_base = base.resolve(strict=True)
            safe_base.relative_to(root)
        except (OSError, ValueError):
            rejected += 1
            continue
        if base.is_symlink() or not safe_base.is_dir():
            rejected += 1
            continue
        for path in sorted(safe_base.rglob('*.md')):
            try:
                relative_candidate = path.relative_to(root)
                if path.is_symlink() or any((root / Path(*relative_candidate.parts[:index])).is_symlink()
                                             for index in range(1, len(relative_candidate.parts))):
                    rejected += 1
                    continue
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
                resolved.relative_to(safe_base)
                if not resolved.is_file() or resolved.suffix != '.md':
                    rejected += 1
                    continue
                yield resolved, resolved.relative_to(root).as_posix(), None
            except (OSError, ValueError):
                rejected += 1
                continue
    yield None, None, rejected


def _source_id(relative_path: str) -> str:
    digest = hashlib.sha256(relative_path.encode('utf-8')).hexdigest()[:24]
    return f'KB-{digest}'


def _display_name(text: str, path: Path) -> str:
    for line in text.splitlines():
        match = _H1_RE.match(line.strip())
        if match:
            return match.group(1).strip()[:200]
    return path.stem[:200]


def _source_result(db, source: LimKnowledgeSource) -> dict:
    active = db.scalar(select(LimKnowledgeSourceVersion).where(
        LimKnowledgeSourceVersion.source_id == source.source_id,
        LimKnowledgeSourceVersion.status == 'active',
    ))
    return {
        'source_id': source.source_id, 'path': source.path, 'display_name': source.display_name,
        'category': source.category, 'summary': source.summary,
        'required_permissions': source.required_permissions or [],
        'is_present': source.is_present, 'is_archived': source.is_archived,
        'active_version': _version_result(active) if active else None,
        'created_at': source.created_at, 'updated_at': source.updated_at,
    }


def _version_result(version: LimKnowledgeSourceVersion) -> dict:
    return {
        'source_id': version.source_id, 'version': version.version,
        'content_hash': version.content_hash, 'status': version.status,
        'valid_from': version.valid_from, 'valid_until': version.valid_until,
        'created_by': version.created_by, 'reviewed_by': version.reviewed_by,
        'reviewed_at': version.reviewed_at, 'created_at': version.created_at,
    }


def _can_read(role, source: LimKnowledgeSource) -> bool:
    if role is None:
        return False
    if role.code == 'admin':
        return True
    return set(source.required_permissions or []) <= set(role.permissions or [])


def sync_knowledge_sources(db, actor, *, repo_root: Path | None = None) -> dict:
    root = (repo_root or _ROOT).resolve()
    found: set[str] = set()
    new_source_count = new_version_count = active_version_count = draft_version_count = unchanged_count = rejected_count = 0
    for path, relative, rejected in _safe_files(root):
        if rejected is not None:
            rejected_count += rejected
            continue
        found.add(relative)
        try:
            raw = path.read_bytes()
            content = raw.decode('utf-8')
        except (OSError, UnicodeError):
            rejected_count += 1
            continue
        digest = hashlib.sha256(raw).hexdigest()
        source = db.scalar(select(LimKnowledgeSource).where(LimKnowledgeSource.path == relative))
        is_new_source = source is None
        if source is None:
            source = LimKnowledgeSource(
                source_id=_source_id(relative), path=relative,
                display_name=_display_name(content, path), category='general', summary='',
                required_permissions=[], is_present=True, is_archived=False, owner_id=actor.id,
            )
            db.add(source)
            db.flush()
            new_source_count += 1
        source.is_present = True
        existing_version = db.scalar(select(LimKnowledgeSourceVersion).where(
            LimKnowledgeSourceVersion.source_id == source.source_id,
            LimKnowledgeSourceVersion.version == digest,
        ))
        if existing_version is not None:
            unchanged_count += 1
            continue

        chunks = _read_chunks(path, relative, content)
        if not chunks:
            rejected_count += 1
            if is_new_source:
                db.delete(source)
            continue
        first_version = db.scalar(select(LimKnowledgeSourceVersion.id).where(
            LimKnowledgeSourceVersion.source_id == source.source_id,
        )) is None
        status = 'active' if first_version and not source.is_archived else 'draft'
        version = LimKnowledgeSourceVersion(
            source_id=source.source_id, version=digest, content_hash=digest, status=status,
            valid_from=None, valid_until=None, created_by=actor.id,
            reviewed_by=actor.id if status == 'active' else None,
            reviewed_at=m.now() if status == 'active' else None,
        )
        db.add(version)
        db.flush()
        for index, chunk in enumerate(chunks, 1):
            chunk_digest = hashlib.sha256(chunk['text'].encode('utf-8')).hexdigest()
            chunk_id = f'C-{index:04d}-{chunk_digest[:16]}'
            db.add(LimKnowledgeChunk(
                source_id=source.source_id, version=digest, chunk_id=chunk_id,
                section=chunk['section'][:200], start_line=chunk['start_line'], end_line=chunk['end_line'],
                text=chunk['text'], content_hash=chunk_digest,
            ))
        new_version_count += 1
        active_version_count += status == 'active'
        draft_version_count += status == 'draft'

    existing_sources = db.scalars(select(LimKnowledgeSource)).all()
    missing_count = 0
    for source in existing_sources:
        present = source.path in found
        if source.is_present != present:
            source.is_present = present
            missing_count += not present
    result = {
        'source_count': len(found), 'new_source_count': new_source_count,
        'new_version_count': new_version_count, 'active_version_count': active_version_count,
        'draft_version_count': draft_version_count, 'unchanged_count': unchanged_count,
        'missing_count': missing_count, 'rejected_count': rejected_count,
    }
    record_audit(db, actor, 'lim_knowledge_sources', 'catalog', 'sync', after=result)
    return result


def visible_knowledge_sources(db, user) -> list[dict]:
    role = role_for(db, user)
    if role is None or (role.code != 'admin' and 'assistant:read' not in role.permissions):
        raise LimRuntimeError('KNOWLEDGE_PERMISSION_REQUIRED', '当前账号无知识检索权限', status_code=403)
    sources = db.scalars(select(LimKnowledgeSource).order_by(LimKnowledgeSource.path)).all()
    return [_source_result(db, source) for source in sources if _can_read(role, source)]


def get_visible_source(db, user, source_id: str) -> LimKnowledgeSource:
    role = role_for(db, user)
    if role is None or (role.code != 'admin' and 'assistant:read' not in role.permissions):
        raise LimRuntimeError('KNOWLEDGE_PERMISSION_REQUIRED', '当前账号无知识检索权限', status_code=403)
    source = db.scalar(select(LimKnowledgeSource).where(LimKnowledgeSource.source_id == source_id))
    if source is None or not _can_read(role, source):
        raise LimRuntimeError('KNOWLEDGE_SOURCE_NOT_FOUND', '知识来源不存在或不可访问', status_code=404)
    return source


def activate_knowledge_version(db, actor, source_id: str, version: str, *, valid_from=None,
                               valid_until=None, no_expiry: bool = False) -> LimKnowledgeSourceVersion:
    source = db.scalar(select(LimKnowledgeSource).where(
        LimKnowledgeSource.source_id == source_id, LimKnowledgeSource.is_archived.is_(False),
    ))
    target = db.scalar(select(LimKnowledgeSourceVersion).where(
        LimKnowledgeSourceVersion.source_id == source_id, LimKnowledgeSourceVersion.version == version,
    ))
    if source is None or target is None:
        raise LimRuntimeError('KNOWLEDGE_VERSION_NOT_FOUND', '来源或版本不存在、已归档', status_code=404)
    if db.scalar(select(LimKnowledgeChunk.id).where(
        LimKnowledgeChunk.source_id == source_id, LimKnowledgeChunk.version == version,
    ).limit(1)) is None:
        raise LimRuntimeError('KNOWLEDGE_VERSION_EMPTY', '空内容版本不能激活', status_code=422)
    if target.status == 'draft' and valid_until is None and not no_expiry:
        raise LimRuntimeError('KNOWLEDGE_VALIDITY_REQUIRED', '请设置有效期或明确确认不自动到期', status_code=422)
    def as_utc_naive(value):
        if value is None:
            return None
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    target.valid_from = as_utc_naive(valid_from)
    target.valid_until = as_utc_naive(valid_until)
    now = m.now()
    if target.valid_from is not None and target.valid_from > now:
        raise LimRuntimeError('KNOWLEDGE_VERSION_NOT_YET_VALID', '尚未生效的版本不能立即激活', status_code=422)
    if target.valid_until is not None and target.valid_until <= now:
        raise LimRuntimeError('KNOWLEDGE_VERSION_EXPIRED', '已到期的知识版本不能激活', status_code=422)
    previous = db.scalars(select(LimKnowledgeSourceVersion).where(
        LimKnowledgeSourceVersion.source_id == source_id,
        LimKnowledgeSourceVersion.status == 'active',
    )).all()
    archived_versions = [row.version for row in previous]
    db.execute(update(LimKnowledgeSourceVersion).where(
        LimKnowledgeSourceVersion.source_id == source_id,
        LimKnowledgeSourceVersion.status == 'active',
    ).values(status='archived').execution_options(synchronize_session=False))
    db.flush()
    for row in previous:
        row.status = 'archived'
    before = target.status
    target.status = 'active'
    target.reviewed_by = actor.id
    target.reviewed_at = m.now()
    record_audit(db, actor, 'lim_knowledge_sources', source_id, 'activate_version',
                 before={'version': version, 'status': before},
                 after={'version': version, 'status': 'active', 'archived_versions': archived_versions})
    return target


def update_knowledge_source(db, actor, source_id: str, changes: dict) -> LimKnowledgeSource:
    source = db.scalar(select(LimKnowledgeSource).where(LimKnowledgeSource.source_id == source_id))
    if source is None:
        raise LimRuntimeError('KNOWLEDGE_SOURCE_NOT_FOUND', '知识来源不存在', status_code=404)
    allowed = {'display_name', 'category', 'summary', 'required_permissions'}
    if not changes or set(changes) - allowed:
        raise LimRuntimeError('KNOWLEDGE_METADATA_INVALID', '知识来源元数据无效', status_code=422)
    before = {key: getattr(source, key) for key in changes}
    for key, value in changes.items():
        setattr(source, key, value)
    record_audit(db, actor, 'lim_knowledge_sources', source_id, 'update_metadata',
                 before=before, after=changes)
    return source


def archive_knowledge_version(db, actor, source_id: str, version: str) -> LimKnowledgeSourceVersion:
    row = db.scalar(select(LimKnowledgeSourceVersion).where(
        LimKnowledgeSourceVersion.source_id == source_id,
        LimKnowledgeSourceVersion.version == version,
    ))
    if row is None:
        raise LimRuntimeError('KNOWLEDGE_VERSION_NOT_FOUND', '知识版本不存在', status_code=404)
    if row.status == 'active':
        raise LimRuntimeError('KNOWLEDGE_VERSION_ACTIVE', '请先激活其他版本或归档整个来源', status_code=409)
    before = row.status
    row.status = 'archived'
    record_audit(db, actor, 'lim_knowledge_sources', source_id, 'archive_version',
                 before={'version': version, 'status': before}, after={'version': version, 'status': 'archived'})
    return row


def version_results_with_diff(db, source: LimKnowledgeSource) -> list[dict]:
    versions = db.scalars(select(LimKnowledgeSourceVersion).where(
        LimKnowledgeSourceVersion.source_id == source.source_id,
    ).order_by(LimKnowledgeSourceVersion.created_at.desc())).all()
    active = next((item for item in versions if item.status == 'active'), None)
    active_hashes = set()
    if active:
        active_hashes = set(db.scalars(select(LimKnowledgeChunk.content_hash).where(
            LimKnowledgeChunk.source_id == source.source_id, LimKnowledgeChunk.version == active.version,
        )).all())
    results = []
    for version in versions:
        hashes = set(db.scalars(select(LimKnowledgeChunk.content_hash).where(
            LimKnowledgeChunk.source_id == source.source_id, LimKnowledgeChunk.version == version.version,
        )).all())
        result = _version_result(version)
        if version.status == 'draft':
            result['diff_summary'] = {
                'added_chunks': len(hashes - active_hashes),
                'removed_chunks': len(active_hashes - hashes),
                'unchanged_chunks': len(hashes & active_hashes),
                'compared_to': active.version if active else None,
            }
        results.append(result)
    return results


def search_registered_knowledge(db, user, query: str, *, limit: int = 5) -> dict:
    query = str(query or '').strip()[:300]
    query_tokens = _tokens(query)
    if not query_tokens:
        raise ValueError('知识检索需要关键词')
    role = role_for(db, user)
    if role is None or (role.code != 'admin' and 'assistant:read' not in role.permissions):
        raise ValueError('当前账号无知识检索权限')
    now = m.now()
    rows = db.execute(
        select(LimKnowledgeChunk, LimKnowledgeSource, LimKnowledgeSourceVersion)
        .join(LimKnowledgeSource, LimKnowledgeSource.source_id == LimKnowledgeChunk.source_id)
        .join(LimKnowledgeSourceVersion, (LimKnowledgeSourceVersion.source_id == LimKnowledgeChunk.source_id)
              & (LimKnowledgeSourceVersion.version == LimKnowledgeChunk.version))
        .where(LimKnowledgeSource.is_archived.is_(False), LimKnowledgeSourceVersion.status == 'active',
               or_(LimKnowledgeSourceVersion.valid_from.is_(None), LimKnowledgeSourceVersion.valid_from <= now),
               or_(LimKnowledgeSourceVersion.valid_until.is_(None), LimKnowledgeSourceVersion.valid_until > now))
        .order_by(LimKnowledgeChunk.source_id, LimKnowledgeChunk.start_line)
    ).all()
    visible = [(chunk, source, version) for chunk, source, version in rows if _can_read(role, source)]
    doc_tokens = [_tokens(f'{source.path}\n{chunk.section}\n{chunk.text}') for chunk, source, _ in visible]
    df: dict[str, int] = {}
    for tokens in doc_tokens:
        for token in tokens:
            df[token] = df.get(token, 0) + 1
    count = len(visible)
    idf = {token: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
           for token, frequency in df.items()}
    query_weight = sum(idf.get(token, 0.0) for token in query_tokens) or 1.0
    normalized_query = re.sub(r'\s+', '', query.casefold())
    ranked = []
    for row, tokens in zip(visible, doc_tokens):
        chunk, source, version = row
        overlap = query_tokens & tokens
        if not overlap:
            continue
        score = sum(idf.get(token, 0.0) for token in overlap) / query_weight
        searchable = re.sub(r'\s+', '', f'{source.path} {chunk.section} {chunk.text}').casefold()
        if normalized_query and normalized_query in searchable:
            score += 0.35
        ranked.append((score, source.path, chunk.start_line, chunk, source, version))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    items = []
    for score, _, _, chunk, source, version in ranked[:max(1, min(limit, 20))]:
        ref_id = f'{source.source_id}:{version.version}:{chunk.chunk_id}'
        items.append({
            'ref_id': ref_id, 'source_id': source.source_id, 'source_version': version.version,
            'chunk_id': chunk.chunk_id, 'content_hash': version.content_hash,
            'path': source.path, 'display_name': source.display_name, 'category': source.category,
            'start_line': chunk.start_line, 'end_line': chunk.end_line,
            'section': chunk.section, 'excerpt': chunk.text, 'relevance': round(score, 4),
            'valid_from': version.valid_from, 'valid_until': version.valid_until,
        })
    return {
        'source': 'LIM 已审核本地 Markdown 知识源（词面检索）', 'query': query,
        'retrieval': 'lexical', 'items': items,
        'limitations': [
            '仅检索已登记、当前生效且账号有权访问的本地 Markdown 快照，不是语义向量检索或联网搜索。',
            '片段用于辅助解释；业务状态、库存和权限以实时业务查询工具为准。',
        ],
    }
