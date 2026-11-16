"""Input contracts and the structure required by the renderers."""
from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parent


class PresentationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def schema(name):
    return json.loads((ROOT / 'contracts' / f'{name}.schema.json').read_text())


def validate(name, value):
    try:
        Draft202012Validator(schema(name), format_checker=FormatChecker()).validate(value)
    except ValidationError as exc:
        # Avoid embedding model output or private analysis in error messages.
        path = getattr(exc, 'json_path', None) or '/'.join(str(v) for v in exc.absolute_path)[:120] or 'root'
        detail = f'{name}: {path[:160]} 不符合契约'
        if exc.validator in ('maxItems', 'minItems', 'maxLength', 'minLength',
                             'enum', 'const', 'type', 'required', 'pattern'):
            detail += f'（{exc.validator}={exc.validator_value}）'
        raise PresentationError('invalid_request' if name == 'request' else 'invalid_deck',
                                detail) from None


def normalize_request(value):
    validate('request', value)
    value = copy.deepcopy(value)
    value.setdefault('locale', 'zh-CN')
    value.setdefault('max_slides', value.get('requested_slides', 8))
    if value.get('requested_slides') is not None:
        if value['requested_slides'] > value['max_slides']:
            raise PresentationError('invalid_request', '指定页数超过 max_slides')
        value['max_slides'] = value['requested_slides']
    if not value['analysis'].strip() or ('title' in value and not value['title'].strip()):
        raise PresentationError('invalid_request', '分析或标题不能为空白')
    ids = [s['id'] for s in value['sources']]
    if len(set(ids)) != len(ids):
        raise PresentationError('invalid_request', '来源 ID 重复')
    return value


def width(text):
    return sum(1 if unicodedata.east_asian_width(c) in 'WF' else .55 for c in text)


def wrap(text, columns):
    """Deterministic CJK-aware wrapping shared by both renderers."""
    lines, line, size = [], '', 0
    for c in text:
        w = width(c)
        if c == '\n' or (line and size + w > columns):
            lines.append(line)
            line, size = '', 0
        if c != '\n':
            line += c
            size += w
    lines.append(line)
    return lines


SOURCE_COLUMNS = 45
SOURCE_PAGE_LINES = 16
# Tables use a smaller face and the full remaining slide height; text pages stay 22pt.
TABLE_FONT_SIZE = 14
TABLE_COLUMNS = 54
TABLE_HEIGHT = 4.7
TABLE_ROW_BASE = .2
TABLE_ROW_LINE = .29 * TABLE_FONT_SIZE / 18


def source_line(source):
    """Compact, deterministic source-page line; full descriptions stay in request.json."""
    parts = [f"[{source['id']}] {source['title']}"]
    try:
        meta = json.loads(source['description'])
    except (TypeError, ValueError):
        meta = None
    if isinstance(meta, dict):
        details = [str(meta[key]) for key in ('index_code', 'unit', 'frequency')
                   if isinstance(meta.get(key), str) and meta[key]]
        if details:
            parts.append(' · '.join(details))
    elif isinstance(source['description'], str):
        text = re.sub(r'\s+', ' ', source['description']).strip()
        if text:
            parts.append(text[:60] + ('…' if len(text) > 60 else ''))
    if source.get('data_date'):
        parts.append('数据日期 ' + source['data_date'])
    url = source.get('url')
    if isinstance(url, str) and url:
        parts.append(url if len(url) <= 80 else url[:77] + '…')
    return ' · '.join(parts)


def source_pages(request):
    """Split compact source lines into fixed-capacity pages instead of clipping."""
    entries = [source_line(source) for source in request['sources']] or ['未提供数据来源']
    chunks, current, lines = [], [], 0
    for entry in entries:
        size = len(wrap(entry, SOURCE_COLUMNS))
        if size > SOURCE_PAGE_LINES:
            raise PresentationError('layout_overflow', '来源条目过长，无法放入固定版式')
        if current and lines + size > SOURCE_PAGE_LINES:
            chunks.append(current)
            current, lines = [], 0
        current.append(entry)
        lines += size
    chunks.append(current)
    return chunks


def checked_deck(request, deck):
    deck = copy.deepcopy(deck)
    # Older saved decks remain renderable, but no longer require evidence fields.
    if isinstance(deck, dict) and isinstance(deck.get('slides'), list):
        for slide in deck['slides']:
            if isinstance(slide, dict) and isinstance(slide.get('blocks'), list):
                for block in slide['blocks']:
                    if isinstance(block, dict):
                        block.pop('evidence_quote', None)
                        block.pop('source_ids', None)
    validate('deck', deck)
    if request.get('title'):
        deck['title'] = request['title']
    if len(deck['slides']) + 1 + len(source_pages(request)) > request['max_slides']:
        raise PresentationError('layout_overflow', '页数超过 max_slides')
    if request.get('requested_slides') is not None and len(deck['slides']) + 1 + len(source_pages(request)) != request['requested_slides']:
        raise PresentationError('layout_overflow', '演示总页数必须为 ' + str(request['requested_slides']) + ' 页（含封面与来源）')
    for slide in deck['slides']:
        blocks, layout = slide['blocks'], slide['layout']
        valid = ((layout == 'bullets' and len(blocks) == 1 and blocks[0]['type'] == 'bullets')
                 or (layout == 'table' and len(blocks) == 1 and blocks[0]['type'] == 'table')
                 or (layout == 'two_column' and len(blocks) == 2
                     and all(b['type'] in ('paragraph', 'bullets') for b in blocks))
                 or (layout in ('kpi', 'chart', 'process', 'matrix') and len(blocks) == 1 and blocks[0]['type'] == layout))
        if not valid:
            raise PresentationError('invalid_deck', '版式与内容块不匹配')
        for block in blocks:
            if block['type'] == 'table' and any(len(row) != len(block['headers']) for row in block['rows']):
                raise PresentationError('invalid_deck', '表格列数不一致')
            if block['type'] == 'chart':
                validate_chart(block)
    warnings = ['review_required'] + ([] if request['sources'] else ['sources_missing'])
    return deck, warnings


def pages(request, deck):
    """Resolve a small renderer-neutral view, retaining full sources."""
    result = [{'layout': 'cover', 'title': deck['title'], 'subtitle': deck.get('subtitle', '产业链观察 · 证据与判断'),
               'blocks': [], 'speaker_notes': ''}]
    result.extend(copy.deepcopy(deck['slides']))
    chunks = source_pages(request)
    for number, entries in enumerate(chunks, 1):
        title = '数据来源与说明' if len(chunks) == 1 else f'数据来源与说明（{number}/{len(chunks)}）'
        result.append({'layout': 'sources', 'title': title, 'entries': entries,
                       'blocks': [], 'speaker_notes': ''})
    # Fixed geometry; fail explicitly rather than silently clipping or reducing fonts.
    for page in result:
        if len(wrap(page['title'], 22 if page['layout'] == 'cover' else 28)) > 2:
            raise PresentationError('layout_overflow', '标题过长，无法放入固定版式')
        for block in page['blocks']:
            if block['type'] == 'kpi':
                card_width = (12.03 - .2 * (len(block['items']) - 1)) / len(block['items'])
                if any(len(wrap(item['value'], (card_width - .44) * 72 / 32)) > 1 for item in block['items']):
                    raise PresentationError('layout_overflow', '指标数值过长，请保留简洁数值并将单位单列')
            if page['layout'] == 'two_column' and block.get('heading'):
                texts = block['items'] if block['type'] == 'bullets' else [block['text']]
                if sum(len(wrap(t, 16)) + 1 for t in texts) > 10:
                    raise PresentationError('layout_overflow', '双栏带小标题时正文需更简洁')
            if block['type'] in ('kpi', 'chart', 'process', 'matrix'):
                continue
            columns = 16 if page['layout'] == 'two_column' else 35
            if block['type'] == 'table':
                columns = TABLE_COLUMNS / len(block['headers'])
                rows = [block['headers']] + block['rows']
                if sum(TABLE_ROW_BASE + TABLE_ROW_LINE * max(len(wrap(c, columns)) for c in row)
                       for row in rows) > TABLE_HEIGHT:
                    raise PresentationError('layout_overflow', '表格超过单页容量')
            else:
                texts = block['items'] if block['type'] == 'bullets' else [block['text']]
                lines = sum(len(wrap(t, columns)) + 1 for t in texts)
                if lines > 12:
                    raise PresentationError('layout_overflow', '正文超过固定版式容量')
    return result


def validate_chart(block):
    """One explicit unit per chart; complete finite series, never invented gaps."""
    definition = next(item for item in schema('deck')['properties']['slides']['items']['properties']['blocks']['items']['oneOf']
                      if item['properties']['type'].get('const') == 'chart')
    try:
        Draft202012Validator(definition).validate(block)
    except ValidationError as exc:
        raise PresentationError('invalid_deck', '图表数据结构不完整') from exc
    n = len(block['categories'])
    if any(len(series['values']) != n or any(not math.isfinite(v) for v in series['values']) for series in block['series']):
        raise PresentationError('invalid_deck', '图表分类和数值数量不一致，或含无效数值')
