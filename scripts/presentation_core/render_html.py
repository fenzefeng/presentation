"""Validate authored HTML and package the offline commodity visual system."""
from __future__ import annotations

import re
import json
from html import escape
from html.parser import HTMLParser
from pathlib import Path

from .contracts import PresentationError, ROOT, validate_chart
from . import html_templates

POLICY = ('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
          'style-src \'unsafe-inline\'; script-src \'unsafe-inline\'; img-src data:; '
          'connect-src \'none\'; base-uri \'none\'; form-action \'none\'">')


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.slide_count = 0
        self.tags = set()
        self.commodity = False
        self.template_id = None
        self.body_attrs = {}
        self.theme_body = False
        self.decks = 0
        self.charts = []
        self.chart_panels = 0
        self._chart = None

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        attrs = dict(attrs)
        if tag == 'body':
            self.body_attrs = attrs
        if tag == 'meta' and attrs.get('name') == 'presentation-template':
            self.template_id = attrs.get('content')
        if tag == 'body' and attrs.get('data-theme') == 'commodity':
            self.theme_body = True
        if 'deck' in attrs.get('class', '').split():
            self.decks += 1
        if 'chart-panel' in attrs.get('class', '').split():
            self.chart_panels += 1
        if tag == 'meta' and attrs.get('name') == 'presentation-theme':
            self.commodity = attrs.get('content') == 'commodity-v2'
        if tag == 'script':
            if attrs.get('type') == 'application/json' and 'chart-data' in attrs.get('class', '').split():
                self._chart = ''
        if 'slide' in attrs.get('class', '').split():
            self.slide_count += 1

    def handle_data(self, data):
        if self._chart is not None:
            self._chart += data

    def handle_endtag(self, tag):
        if tag == 'script' and self._chart is not None:
            self.charts.append(self._chart)
            self._chart = None


def normalize(content, request, *, template=None):
    if not isinstance(content, str):
        raise PresentationError('invalid_html', 'HTML 模型响应必须为文本')
    content = content.lstrip('\ufeff\u200b\u200c\u200d\u2060').strip()
    fenced = re.fullmatch(r'```(?:html)?\s*\n([\s\S]*?)\n```', content, re.IGNORECASE)
    if fenced:
        content = fenced.group(1).strip()
    # Models sometimes place the inline script after </body>. Browsers accept
    # that placement; requiring adjacent body/html closers rejects useful code.
    if (len(content.encode()) > 262144 or not re.match(r'<!doctype\s+html\s*>', content, re.I)
            or not re.search(r'</body>', content, re.I) or not re.search(r'</html>\s*$', content, re.I)):
        raise PresentationError('invalid_html', '需要完整的 HTML 文档，不能是片段或截断响应')
    head = re.search(r'<head\s*>', content, re.I)
    if not head or not re.search(r'</head>', content, re.I):
        raise PresentationError('invalid_html', 'HTML 缺少 head')
    doc = Document()
    doc.feed(content)
    if not {'html', 'head', 'title', 'body'} <= doc.tags or doc.slide_count < 3:
        raise PresentationError('invalid_html', 'HTML 需包含标题及至少三页 class="slide"')
    if doc.slide_count > request['max_slides']:
        raise PresentationError('layout_overflow', 'HTML 页数超过 max_slides')
    if request.get('requested_slides') is not None and doc.slide_count != request['requested_slides']:
        raise PresentationError('layout_overflow', 'HTML 总页数必须为 ' + str(request['requested_slides']) + ' 页（含封面与来源）')
    if doc.commodity:
        if not doc.theme_body or doc.decks != 1:
            raise PresentationError('invalid_html', '研报主题需要 body data-theme="commodity" 和唯一 class="deck" 容器')
        if doc.chart_panels != len(doc.charts):
            raise PresentationError('invalid_html', '每个 chart-panel 必须包含一个 <script class="chart-data" type="application/json"> 的完整图表数据；不要用可执行 JS 绘图，也不要留下空白图框')
        for chart in doc.charts:
            try:
                validate_chart(json.loads(chart))
            except (ValueError, TypeError):
                raise PresentationError('invalid_html', '图表必须包含完整的 JSON 数据') from None
        # Models may redundantly add navigation or styles despite the prompt.
        # The v2 theme owns both. Keep validated chart JSON, replace everything
        # else instead of rejecting an otherwise complete presentation.
        def chart_only(match):
            fragment = Document()
            fragment.feed(match.group(0))
            return match.group(0) if fragment.charts else ''
        content = re.sub(r'<script\b[^>]*>[\s\S]*?</script\s*>\s*', chart_only, content, flags=re.I)
        content = re.sub(r'<style\b[^>]*>[\s\S]*?</style\s*>\s*', '', content, flags=re.I)
        profile = html_templates.selected(template or doc.template_id)
        attrs = dict(doc.body_attrs)
        known_classes = {p['body_class'] for p in html_templates.registry()['templates'].values() if p['body_class']}
        classes = [c for c in attrs.get('class', '').split() if c not in known_classes]
        if profile['body_class']:
            classes.append(profile['body_class'])
        if classes:
            attrs['class'] = ' '.join(classes)
        else:
            attrs.pop('class', None)
        attrs['data-template'] = profile['name']
        body = '<body' + ''.join(' ' + k + ('="' + escape(v, quote=True) + '"' if v is not None else '') for k, v in attrs.items()) + '>'
        content = re.sub(r'<body\b[^>]*>', lambda _: body, content, count=1, flags=re.I)
        content = re.sub(r'<meta\b[^>]*\bname\s*=\s*[\'\"]presentation-template[\'\"][^>]*>\s*', '', content, flags=re.I)
        css = html_templates.styles(profile)
        js = (ROOT / 'visuals/commodity.js').read_text(encoding='utf-8')
        marker = '<meta name="presentation-template" content="' + profile['name'] + '">\n'
        content = re.sub(r'</head>', lambda _: marker + '<style id="commodity-theme">' + css + '</style>\n</head>', content, count=1, flags=re.I)
        content = re.sub(r'</body>', lambda _: '<script id="commodity-runtime">' + js + '</script>\n</body>', content, count=1, flags=re.I)
    # Legacy unmarked HTML keeps authored CSS/JS. All modes get a network policy.
    # This is not a sanitizer: future web previews must also use an isolated iframe.
    if not content[head.end():].lstrip().startswith(POLICY):
        content = content[:head.end()] + '\n' + POLICY + content[head.end():]
    return content, doc.slide_count


def render(content: str, output: Path):
    output.write_text(content, encoding='utf-8')


def verify(output: Path, expected_pages: int):
    doc = Document()
    doc.feed(output.read_text(encoding='utf-8'))
    if doc.slide_count != expected_pages:
        raise PresentationError('invalid_html', '保存后的 HTML 页数不匹配')
