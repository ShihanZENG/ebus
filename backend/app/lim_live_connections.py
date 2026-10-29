"""Explicit exports of scoped, persisted evidence to configured external services.

No default hosts or credentials. These routes never execute client-supplied Cypher,
send payment documents, or fabricate model usage. ERP remains the authority.
"""
import hashlib
import json
import math
import os
import re
from datetime import timezone
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from . import lim_models as lm
from .lim_live import router, authorized_run
from .lim_live_views import graph_snapshot
from .security import require, session_db, record_audit

CONFIG = {
    'neo4j': ['LIM_NEO4J_URI', 'LIM_NEO4J_USER', 'LIM_NEO4J_PASSWORD'],
    'langfuse': ['LIM_LANGFUSE_HOST', 'LIM_LANGFUSE_PUBLIC_KEY', 'LIM_LANGFUSE_SECRET_KEY'],
    'otel': ['LIM_OTEL_TRACES_ENDPOINT'],
}
VECTOR_DIMENSIONS = 64
VECTOR_INDEX = 'lim_live_claim_vector_v1'
DOMAIN_WORDS = {
    'product': '商品 产品 sku', 'inventory': '库存 可售 缺货 stock',
    'procurement': '采购 供应商 在途 purchase supplier',
    'ads': '广告 投放 花费 campaign spend', 'finance': '财务 核验 收款 payment',
}


def evidence_text(ref):
    claim = str(ref.get('claim_key', ''))
    domain = claim.split('.')[0]
    subject = ref.get('subject') or {}
    return ' '.join([claim, DOMAIN_WORDS.get(domain, ''), str(ref.get('source', '')),
        *(str(value) for value in subject.values()), str(ref.get('value', ''))])[:2000]


def evidence_vector(value):
    """Stable, local token-hash vector; no model or external embedding service required."""
    tokens = re.findall(r'[a-z0-9_]+|[\u4e00-\u9fff]', value.casefold())
    vector = [0.0] * VECTOR_DIMENSIONS
    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], 'big') % VECTOR_DIMENSIONS
        vector[index] += 1.0 if digest[4] & 1 else -1.0
    magnitude = math.sqrt(sum(component * component for component in vector))
    return [component / magnitude for component in vector] if magnitude else vector


def configured(service):
    return all(os.getenv(key) for key in CONFIG[service])


@router.get('/connections')
def connection_status(user=Depends(require('assistant:read'))):
    result = {key: {'configured': configured(key), 'connection_verified': False}
              for key in CONFIG}
    if configured('neo4j'):
        try:
            with neo4j_driver() as driver:
                driver.verify_connectivity()
                with driver.session(database=os.getenv('LIM_NEO4J_DATABASE', 'neo4j')) as session:
                    indexes = session.run('SHOW VECTOR INDEXES YIELD name, state '
                        'WHERE name = $name RETURN state', name=VECTOR_INDEX)
                    state = next((row['state'] for row in indexes), None)
            result['neo4j'].update(connection_verified=True, vector_index_state=state)
        except Exception:
            result['neo4j']['error'] = 'Neo4j 连接失败'
    return result


def neo4j_driver():
    from neo4j import GraphDatabase
    return GraphDatabase.driver(os.environ['LIM_NEO4J_URI'],
        auth=(os.environ['LIM_NEO4J_USER'], os.environ['LIM_NEO4J_PASSWORD']),
        connection_timeout=5, connection_acquisition_timeout=5, max_transaction_retry_time=5)


def export_graph(db, user, run_id):
    snapshot = graph_snapshot(db, user, run_id)
    scope = hashlib.sha256(f'{user.id}:{run_id}'.encode()).hexdigest()
    labels = {node['id']: node['label'] for node in snapshot['entities']}
    claim_labels = {}
    for edge in snapshot['edges']:
        claim_labels.setdefault(edge['target'], []).append(labels[edge['source']])
    def indexed_text(ref):
        return (evidence_text(ref) + ' ' + ' '.join(claim_labels.get(ref['ref_id'], [])))[:2000]
    claims = [{'key': scope + ':' + ref['ref_id'], 'payload': json.dumps(ref, ensure_ascii=False),
               'version': ref['version'], 'observed_at': ref['observed_at'],
               'search_text': indexed_text(ref), 'embedding': evidence_vector(indexed_text(ref))}
              for ref in snapshot['claims']]
    edges = [{'entity_key': scope + ':' + edge['source'], 'claim_key': scope + ':' + edge['target']}
             for edge in snapshot['edges']]
    entities = [{'key': scope + ':' + item['id'], 'kind': item['type'], 'value': str(item['value'])}
                for item in snapshot['entities']]
    with neo4j_driver() as driver, driver.session(database=os.getenv('LIM_NEO4J_DATABASE', 'neo4j')) as session:
        session.run('CREATE VECTOR INDEX ' + VECTOR_INDEX + ' IF NOT EXISTS '
            'FOR (c:LimLiveClaim) ON (c.embedding) OPTIONS {indexConfig: '
            '{`vector.dimensions`: 64, `vector.similarity_function`: \'cosine\'}}').consume()
        def write(tx):
            tx.run('UNWIND $claims AS c MERGE (n:LimLiveClaim {key:c.key}) '
                'SET n.scope=$scope,n.payload=c.payload,n.version=c.version,n.observed_at=c.observed_at,'
                'n.search_text=c.search_text,n.embedding=c.embedding',
                claims=claims, scope=scope).consume()
            tx.run('UNWIND $entities AS e MERGE (n:LimLiveEntity {key:e.key}) '
                'SET n.scope=$scope,n.kind=e.kind,n.value=e.value', entities=entities, scope=scope).consume()
            tx.run('UNWIND $edges AS e MATCH (n:LimLiveEntity {key:e.entity_key}),'
                '(c:LimLiveClaim {key:e.claim_key}) MERGE (n)-[:HAS_EVIDENCE]->(c)', edges=edges).consume()
        session.execute_write(write)
    return {'service': 'neo4j', 'status': 'exported', 'claims': len(claims), 'entities': len(entities)}


class GraphSearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=200)
    top_k: int = Field(default=12, ge=1, le=30)
    as_of: str | None = None


def search_graph(db, user, run_id, request: GraphSearchRequest):
    snapshot = graph_snapshot(db, user, run_id, as_of=request.as_of)
    if not configured('neo4j'):
        raise HTTPException(503, 'Neo4j 未配置')
    # Idempotent synchronization lets historical runs become searchable too.
    export_graph(db, user, run_id)
    scope = hashlib.sha256(f'{user.id}:{run_id}'.encode()).hexdigest()
    vector = evidence_vector(request.query)
    if not any(vector):
        raise HTTPException(422, '请输入可检索的关键词')
    with neo4j_driver() as driver, driver.session(database=os.getenv('LIM_NEO4J_DATABASE', 'neo4j')) as session:
        rows = session.run('MATCH (c:LimLiveClaim {scope:$scope}) '
            'RETURN c.key AS key, c.search_text AS text, '
            'vector.similarity.cosine(c.embedding,$vector) AS vector_score',
            scope=scope, vector=vector)
        candidates = [{'ref_id': row['key'].split(':')[-1], 'text': row['text'],
                       'vector_score': float(row['vector_score'] or 0)} for row in rows]
    valid = {ref['ref_id'] for ref in snapshot['claims']}
    candidates = [item for item in candidates if item['ref_id'] in valid]
    words = re.findall(r'[a-z0-9_]+|[\u4e00-\u9fff]', request.query.casefold())
    for item in candidates:
        item['keyword_score'] = sum(item['text'].casefold().count(word) for word in words)
    vector_order = sorted(candidates, key=lambda item: (-item['vector_score'], item['ref_id']))
    keyword_order = sorted((item for item in candidates if item['keyword_score']),
                           key=lambda item: (-item['keyword_score'], item['ref_id']))
    scores = {item['ref_id']: 1 / (60 + rank) for rank, item in enumerate(vector_order, 1)}
    for rank, item in enumerate(keyword_order, 1):
        scores[item['ref_id']] += 1 / (60 + rank)
    selected = sorted(candidates, key=lambda item: (-scores[item['ref_id']], item['ref_id']))[:request.top_k]
    wanted = {item['ref_id'] for item in selected}
    snapshot['claims'] = [ref for ref in snapshot['claims'] if ref['ref_id'] in wanted]
    snapshot['edges'] = [edge for edge in snapshot['edges'] if edge['target'] in wanted]
    node_ids = {edge['source'] for edge in snapshot['edges']}
    snapshot['entities'] = [node for node in snapshot['entities'] if node['id'] in node_ids]
    snapshot['relations'] = [relation for relation in snapshot['relations']
                             if relation['evidence_ref'] in wanted]
    snapshot['backend'] = 'neo4j'
    snapshot['retrieval'] = 'scoped Neo4j cosine vector + keyword ranking (RRF)'
    snapshot['embedding'] = 'local token-hash-v1; lexical similarity, not a semantic language model'
    snapshot['matches'] = [{key: item[key] for key in ('ref_id', 'vector_score', 'keyword_score')}
                           for item in selected]
    snapshot['limitations'] = ['向量使用本地词元哈希，同义词语义匹配能力有限',
                               '时间过滤依据检查点观察时间，不推断业务有效期']
    return snapshot


@router.post('/runs/{run_id}/graph/search')
def graph_search_route(run_id: str, body: GraphSearchRequest, db=Depends(session_db),
                       user=Depends(require('assistant:read'))):
    authorized_run(db, user, run_id)
    try:
        return search_graph(db, user, run_id, body)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, '图谱检索失败；请检查 Neo4j 服务') from None


@router.get('/runs/{run_id}/graph/neo4j')
def neo4j_read(run_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    authorized_run(db, user, run_id)
    if not configured('neo4j'):
        raise HTTPException(503, 'Neo4j 未配置')
    scope = hashlib.sha256(f'{user.id}:{run_id}'.encode()).hexdigest()
    try:
        from neo4j import Query
        with neo4j_driver() as driver, driver.session(database=os.getenv('LIM_NEO4J_DATABASE', 'neo4j')) as session:
            rows = session.run(Query('MATCH (e:LimLiveEntity {scope:$scope})-[:HAS_EVIDENCE]->'
                '(c:LimLiveClaim {scope:$scope}) RETURN e.kind AS kind,e.value AS value,c.payload AS claim LIMIT 1000',
                timeout=10), scope=scope)
            items = [{'entity_type': row['kind'], 'entity_value': row['value'],
                      'claim': json.loads(row['claim'])} for row in rows]
        return {'backend': 'neo4j', 'items': items, 'limit': 1000}
    except Exception:
        raise HTTPException(503, 'Neo4j 查询失败；请检查服务配置和服务端日志') from None


def export_telemetry(db, live, service):
    calls = db.scalars(select(lm.LimToolInvocation).where(lm.LimToolInvocation.run_id.in_(live.child_run_ids))).all()
    if service == 'langfuse':
        from . import models as m
        from .lim_live_observability import read_observability, send_langfuse
        from langfuse import Langfuse
        client = Langfuse(host=os.environ['LIM_LANGFUSE_HOST'], public_key=os.environ['LIM_LANGFUSE_PUBLIC_KEY'],
                         secret_key=os.environ['LIM_LANGFUSE_SECRET_KEY'], timeout=5)
        if not client.auth_check():
            raise RuntimeError('Langfuse authentication failed')
        report = read_observability(db, db.get(m.User, live.actor_id), live.id)
        return send_langfuse(report, client)
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    provider = TracerProvider(resource=Resource.create({'service.name': 'ebus-lim-live'}))
    memory = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    tracer = provider.get_tracer('lim-live-export')
    for call in calls:
        start = int(call.created_at.replace(tzinfo=timezone.utc).timestamp() * 1_000_000_000)
        span = tracer.start_span(call.tool_id, start_time=start, attributes={
            'lim.run_id': live.id, 'lim.invocation_id': call.invocation_id,
            'lim.status': call.status, 'lim.elapsed_ms': call.elapsed_ms or 0})
        span.end(end_time=start + max(1, call.elapsed_ms or 0) * 1_000_000)
    exporter = OTLPSpanExporter(endpoint=os.environ['LIM_OTEL_TRACES_ENDPOINT'], timeout=5)
    try:
        result = exporter.export(memory.get_finished_spans())
        if result != SpanExportResult.SUCCESS:
            raise RuntimeError('OTLP export rejected')
    finally:
        exporter.shutdown()
        provider.shutdown()
    return {'service': service, 'status': 'accepted', 'span_count': len(calls)}


@router.post('/runs/{run_id}/export/{service}')
def export_route(run_id: str, service: str, db=Depends(session_db), user=Depends(require('lim:manage'))):
    live, _ = authorized_run(db, user, run_id)
    if service not in CONFIG:
        raise HTTPException(404, '服务不存在')
    if not configured(service):
        raise HTTPException(503, f'{service} 未配置；保留数据库记录，不发送外部请求')
    if service in {'langfuse', 'otel'}:
        from .lim_live_models import LiveEvaluation
        from .lim_live_observability import persist_evaluation
        saved = db.scalar(select(LiveEvaluation).where(LiveEvaluation.run_id == run_id))
        if saved is None:
            saved = persist_evaluation(db, run_id)
    if service == 'langfuse':
        previous = (saved.delivery or {}).get('langfuse') if saved else None
        if previous and previous.get('status') == 'submitted':
            return {**previous, 'status': 'already_submitted'}
    try:
        result = export_graph(db, user, run_id) if service == 'neo4j' else export_telemetry(db, live, service)
    except Exception:
        record_audit(db, user, 'lim_live_runs', run_id, 'export_failed', after={'service': service})
        db.commit()
        raise HTTPException(503, f'{service} 导出失败；数据库证据仍然可用') from None
    if service != 'neo4j':
        from .lim_live_observability import mark_delivery
        mark_delivery(db, run_id, service, result)
    record_audit(db, user, 'lim_live_runs', run_id, 'export', after=result)
    db.commit()
    return result
