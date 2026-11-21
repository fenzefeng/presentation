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


def validate(name, value, *, contract=None):
    try:
        Draft202012Validator(contract if contract is not None else schema(name),
                             format_checker=FormatChecker()).validate(value)
    except ValidationError as exc:
        # Avoid embedding model output or private analysis in error messages.
        if name == 'deck' and exc.validator == 'oneOf' and isinstance(exc.instance, dict):
            block_type = exc.instance.get('type')
            exc = next((detail for detail in exc.context
                        if exc.validator_value[detail.schema_path[0]]['properties']['type']['const'] == block_type),
                       exc)
        path = getattr(exc, 'json_path', None) or '/'.join(str(v) for v in exc.absolute_path)[:120] or 'root'
        detail = f'{name}: {path[:160]} 不符合契约'
        if exc.validator in ('maxItems', 'minItems', 'maxLength', 'minLength',
                             'enum', 'const', 'type', 'required', 'pattern'):
            detail += f'（{exc.validator}={exc.validator_value}）'
        elif exc.validator == 'additionalProperties':
            detail += '（含未定义字段）'
        code = {'request': 'invalid_request', 'research': 'invalid_html'}.get(name, 'invalid_deck')
        raise PresentationError(code,
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
    series = value.get('series', [])
    series_ids = [item['source_id'] for item in series]
    if len(set(series_ids)) != len(series_ids) or set(series_ids) - set(ids):
        raise PresentationError('invalid_request', '时序来源不存在或重复')
    if sum(len(item['points']) for item in series) > 1200:
        raise PresentationError('invalid_request', '可展示的观测点总数超过 1200')
    for item in series:
        points = item['points']
        if not item['unit'].strip() or len({day for day, _ in points}) != len(points) or any(
                abs(number) > 1e100 or not math.isfinite(number) for _, number in points):
            raise PresentationError('invalid_request', '时序单位、日期或数值无效')
        points.sort(key=lambda point: point[0])
    return value


def checked_research(request, research, *, allow_legacy=False):
    contract = schema('research')
    legacy = allow_legacy and isinstance(research, dict) and 'title' in research
    if legacy:
        # Previously saved plans remain renderable with the new page layout.
        research = copy.deepcopy(research)
        legacy_title = research.pop('title')
        if 'headline' not in research:
            candidates = (research.get('conclusion'), legacy_title)
            research['headline'] = next((value.strip() for value in candidates if isinstance(value, str)
                                         and 0 < len(value.strip()) <= 32
                                         and not re.search(r'[0-9０-９\r\n]', value.strip())), '主要结论')
        insight_schema = contract['properties']['insights']
        insight_schema['maxItems'] = 8
        insight_schema['items']['properties']['heading'] = {'type': 'string', 'minLength': 1, 'maxLength': 72}
        if isinstance(research.get('insights'), list):
            for insight in research['insights']:
                if isinstance(insight, dict):
                    insight.pop('source_ids', None)
    validate('research', research, contract=contract)
    series_ids = {item['source_id'] for item in request.get('series', [])}
    if set(research.get('focus_ids', [])) - series_ids:
        raise PresentationError('invalid_html', '研究内容引用了未提供的指标')
    headings = [item['heading'] for item in research['insights']]
    if not legacy and len(set(headings)) != len(headings):
        raise PresentationError('invalid_html', '关键解读的价格、库存、供应和需求各最多出现一次')
    fields = [research['headline'], research['conclusion']]
    fields.extend(field for item in research['insights'] for field in (item['heading'], item['text']))
    if any(not field.strip() for field in fields):
        raise PresentationError('invalid_html', '研究标题、结论或解读不能为空白')
    return research


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


# Tables use a smaller face and the full remaining slide height; text pages stay 22pt.
TABLE_FONT_SIZE = 14
TABLE_COLUMNS = 54
TABLE_HEIGHT = 4.7
TABLE_ROW_BASE = .2
TABLE_ROW_LINE = .29 * TABLE_FONT_SIZE / 18


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
    slide_count = len(deck['slides'])
    requested = request.get('requested_slides')
    if requested is not None and slide_count != requested:
        raise PresentationError('layout_overflow', f'演示总页数必须为 {requested} 页')
    if slide_count > request['max_slides']:
        raise PresentationError('layout_overflow', '页数超过 max_slides')
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
    """Add the report heading to the first content slide."""
    result = copy.deepcopy(deck['slides'])
    first = result[0]
    deck_title = ' '.join((request.get('title') or deck['title']).split())
    if deck_title != ' '.join(first['title'].split()):
        first['deck_title'] = deck_title
    if deck.get('subtitle'):
        first['deck_subtitle'] = ' '.join(deck['subtitle'].split())
    # Fixed geometry; fail explicitly rather than silently clipping or reducing fonts.
    for page in result:
        if len(wrap(page['title'], 28)) > 2:
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
