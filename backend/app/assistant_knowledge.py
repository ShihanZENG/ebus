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


def _read_chunks(path, relative, text=None):
    if text is None:
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
    """检索当前用户有权访问的已登记本地 Markdown 知识快照。"""
    from .lim_knowledge import search_registered_knowledge
    return search_registered_knowledge(db, user, (args or {}).get('query', ''))


KNOWLEDGE_TOOL_FUNCTIONS = {'search_knowledge': search_knowledge}
