"""只从审核过的本地 Markdown 文档检索可追溯知识片段。"""

import math
import re
from functools import lru_cache
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_ALLOWED_DOC_DIRS = ('docs/功能章节', 'docs/oms')
_TOKEN_RE = re.compile(r'[a-z0-9_]+|[\u3400-\u9fff]{2,}', re.IGNORECASE)
_HEADING_RE = re.compile(r'^#{1,6}\s+(.+?)\s*#*\s*$')


def _tokens(text):
    """中文用相邻二字片段，英文/编码按词匹配；仅用于词面检索。"""
    result = set()
    for token in _TOKEN_RE.findall(text.casefold()):
        if re.fullmatch(r'[\u3400-\u9fff]+', token):
            result.update(token[i:i + 2] for i in range(len(token) - 1))
            if len(token) == 2:
                result.add(token)
        else:
            result.add(token)
    return result


def _read_chunks(path, relative):
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return []
    chunks = []
    section = path.stem
    buffer = []
    start_line = 1

    def flush(end_line):
        body = '\n'.join(buffer).strip()
        if not body:
            return
        # Keep chunks bounded for model context and make their line ranges auditable.
        paragraphs = re.split(r'\n\s*\n', body)
        piece = ''
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            if len(piece) + len(paragraph) > 1400 and piece:
                chunks.append({'path': relative, 'section': section,
                               'start_line': start_line, 'end_line': end_line,
                               'text': piece[:1400]})
                piece = paragraph
            else:
                piece = f'{piece}\n\n{paragraph}'.strip()
        if piece:
            chunks.append({'path': relative, 'section': section,
                           'start_line': start_line, 'end_line': end_line,
                           'text': piece[:1400]})

    for line_no, line in enumerate(text.splitlines(), 1):
        match = _HEADING_RE.match(line)
        if match:
            flush(line_no - 1)
            buffer.clear()
            section = match.group(1).strip()[:160]
            start_line = line_no
        else:
            if not buffer:
                start_line = line_no
            buffer.append(line)
    flush(len(text.splitlines()))
    return chunks


@lru_cache(maxsize=1)
def _corpus():
    chunks = []
    for directory in _ALLOWED_DOC_DIRS:
        base = _ROOT / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob('*.md')):
            relative = path.relative_to(_ROOT).as_posix()
            chunks.extend(_read_chunks(path, relative))
    return chunks


KNOWLEDGE_TOOLS = [{
    'type': 'function',
    'function': {
        'name': 'search_knowledge',
        'description': '只在已审核的本地功能说明和 OMS 操作文档中检索关键词，返回可引用的章节与原文片段；不是联网搜索。',
        'parameters': {
            'type': 'object',
            'properties': {'query': {'type': 'string', 'description': '要检索的功能、字段或操作关键词'}},
            'required': ['query'],
            'additionalProperties': False,
        },
    },
}]


def search_knowledge(db, user, args):
    """词面检索本地审核文档。db/user 参数与助手工具接口保持一致。"""
    query = str((args or {}).get('query', '')).strip()[:300]
    query_tokens = _tokens(query)
    if len(query_tokens) < 1:
        raise ValueError('知识检索需要关键词')
    corpus = _corpus()
    document_tokens = [
        _tokens(f"{chunk['path']}\n{chunk['section']}\n{chunk['text']}") for chunk in corpus
    ]
    document_frequency = {}
    for tokens in document_tokens:
        for token in tokens:
            document_frequency[token] = document_frequency.get(token, 0) + 1
    idf = {token: math.log(1 + (len(corpus) - count + 0.5) / (count + 0.5))
           for token, count in document_frequency.items()}
    query_weight = sum(idf.get(token, 0.0) for token in query_tokens) or 1.0
    normalized_query = re.sub(r'\s+', '', query.casefold())
    candidates = []
    for chunk, doc_tokens in zip(corpus, document_tokens):
        overlap = query_tokens & doc_tokens
        if not overlap:
            continue
        # Rare query terms carry more weight; a contiguous phrase is a strong precision signal.
        score = sum(idf.get(token, 0.0) for token in overlap) / query_weight
        searchable = re.sub(r'\s+', '', f"{chunk['path']} {chunk['section']} {chunk['text']}").casefold()
        if normalized_query and normalized_query in searchable:
            score += 0.35
        candidates.append((score, chunk))
    candidates.sort(key=lambda row: (-row[0], row[1]['path'], row[1]['start_line']))
    items = []
    for index, (score, chunk) in enumerate(candidates[:5], 1):
        ref_id = f'K{index}'
        items.append({
            'ref_id': ref_id,
            'path': chunk['path'],
            'section': chunk['section'],
            'start_line': chunk['start_line'],
            'end_line': chunk['end_line'],
            'excerpt': chunk['text'],
            'relevance': round(score, 4),
        })
    return {
        'source': '项目本地审核文档（关键词检索）',
        'query': query,
        'retrieval': 'lexical',
        'limitations': ['仅搜索 docs/功能章节 与 docs/oms 下的 Markdown 文件，不是语义向量检索或联网搜索。',
                        '检索片段用于辅助解释；业务状态、库存和权限以实时业务查询工具为准。'],
        'items': items,
    }


KNOWLEDGE_TOOL_FUNCTIONS = {'search_knowledge': search_knowledge}
