"""Editable Chinese commodity research decks; charts keep their workbook data."""
import math
from pathlib import Path

from .contracts import (SOURCE_COLUMNS, TABLE_COLUMNS, TABLE_FONT_SIZE,
                        TABLE_ROW_BASE, TABLE_ROW_LINE, wrap)

FONT = 'Noto Sans CJK SC'
INK, MUTED, TEAL, COPPER = '19343D', '63767B', '087F82', 'B17448'
PAPER, WHITE, LINE, SOFT = 'F5F3ED', 'FFFFFF', 'DCE4E1', 'E9EFEB'


def chart_axis(values, bar=False):
    lo, hi = min(values), max(values)
    if bar:
        lo, hi = min(0, lo), max(0, hi)
    else:
        pad = (hi - lo or abs(hi) * .1 or 1) * .18
        lo, hi = lo - pad, hi + pad
        if min(values) >= 0:
            lo = max(0, lo)
    span = hi - lo or 1
    power = 10 ** math.floor(math.log10(span / 4))
    ratio = span / 4 / power
    step = next(s for s in (1, 2, 5, 10) if ratio <= s) * power
    low, high = math.floor(lo / step) * step, math.ceil(hi / step) * step
    return low, high if high != low else low + step, step


def render(pages, output: Path):
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_MARKER_STYLE, XL_LABEL_POSITION, XL_TICK_MARK
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.oxml.xmlchemy import OxmlElement
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    rgb = RGBColor.from_string

    def style(p, size, color, bold=False):
        p.font.name, p.font.size = FONT, Pt(size)
        p.font.bold, p.font.color.rgb = bold, rgb(color)
        p.line_spacing, p.space_after = 1.25, Pt(0)
        for run in p.runs:
            props = run._r.get_or_add_rPr()
            for tag in ('a:ea', 'a:latin'):
                item = OxmlElement(tag)
                item.set('typeface', FONT)
                props.append(item)

    def box(slide, text, x, y, w, h, size=20, color=INK, bold=False, columns=None):
        shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = shape.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        # Explicit CJK-aware lines prevent OS font fallback changing the layout.
        lines = wrap(text, columns or w * 72 / size) if text else ['']
        for i, line in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = line
            style(p, size, color, bold)
        return shape

    def rect(slide, x, y, w, h, fill=WHITE, border=LINE, rounded=True):
        shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
                                       Inches(x), Inches(y), Inches(w), Inches(h))
        if rounded:
            shape.adjustments[0] = .12
        shape.fill.solid()
        shape.fill.fore_color.rgb = rgb(fill)
        if border:
            shape.line.color.rgb = rgb(border)
            shape.line.width = Pt(.7)
        else:
            shape.line.fill.background()
        return shape

    for i, page in enumerate(pages):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        cover = page['layout'] == 'cover'
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = rgb(INK if cover else PAPER)
        if cover:
            # Contained geometric motif, never a fabricated market trend.
            for x, y, d in ((10.1, 1.25, 2.4), (10.55, 1.7, 1.5)):
                ring = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
                ring.fill.background()
                ring.line.color.rgb = rgb('42616A')
            box(slide, '大宗商品研究 / FUSION', .72, 1.05, 9, .35, 13, '78C7C3', True)
            rect(slide, .72, 1.7, .65, .035, COPPER, None, False)
            box(slide, page['title'], .72, 2.05, 9.2, 2.15, 36, WHITE, True, columns=18)
            box(slide, page.get('subtitle', ''), .75, 4.5, 9.5, 1.0, 19, 'C0D2D3', columns=32)
            box(slide, '研究观点 · 数据依据 · 观察变量', .75, 6.05, 10, .3, 12, 'AAC4C5')
        else:
            eyebrow = page.get('eyebrow') or {'sources': '资料与口径', 'kpi': '关键指标', 'chart': '数据观察',
                       'process': '传导机制', 'matrix': '情景与跟踪'}.get(page['layout'], '研究要点')
            box(slide, eyebrow, .65, .42, 11.9, .26, 11, TEAL, True)
            box(slide, page['title'], .65, .91, 12, .95, 26, INK, True, columns=28)
            if page['layout'] == 'sources':
                text = '\n'.join('\n'.join(wrap(t, SOURCE_COLUMNS)) for t in page['entries'])
                rect(slide, .65, 2.0, 12.03, 4.6)
                box(slide, text, .95, 2.25, 11.4, 4.1, 14, MUTED, columns=SOURCE_COLUMNS)
            for j, block in enumerate(page['blocks']):
                kind = block['type']
                if kind == 'kpi':
                    n = len(block['items'])
                    w = (12.03 - .2 * (n - 1)) / n
                    for k, item in enumerate(block['items']):
                        x = .65 + k * (w + .2)
                        rect(slide, x, 2.35, w, 3.25)
                        rect(slide, x + .22, 2.35, .46, .035, TEAL, None, False)
                        box(slide, item['label'], x + .22, 2.65, w - .44, .7, 15, MUTED)
                        box(slide, item['value'], x + .22, 3.4, w - .44, .7, 32, INK, True)
                        box(slide, item['unit'], x + .22, 4.13, w - .44, .35, 12, MUTED)
                        change = item.get('change', '')
                        # Red/green encode direction in the Chinese market convention.
                        color = 'B84F43' if change.startswith(('+', '↑')) else '277563' if change.startswith(('-', '−', '↓')) else TEAL
                        box(slide, change, x + .22, 4.65, w - .44, .52, 13, color, True)
                        box(slide, item.get('period', ''), x + .22, 5.13, w - .44, .4, 10, MUTED)
                elif kind == 'chart':
                    rect(slide, .65, 1.98, 12.03, 4.42)
                    low, high, step = chart_axis([v for s in block['series'] for v in s['values']], block['kind'] == 'bar')
                    unit = '单位：' + block['unit'] + ('  ·  纵轴非零起点' if block['kind'] == 'line' and low > 0 else '')
                    box(slide, unit, .95, 2.18, 7, .3, 11, MUTED)
                    data = CategoryChartData()
                    data.categories = block['categories']
                    for series in block['series']:
                        data.add_series(series['name'], series['values'])
                    chart = slide.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS if block['kind'] == 'line' else XL_CHART_TYPE.COLUMN_CLUSTERED,
                                                    Inches(.92), Inches(2.57), Inches(11.42), Inches(3.55), data).chart
                    chart.has_legend = True
                    chart.legend.position = XL_LEGEND_POSITION.TOP
                    chart.legend.include_in_layout = True
                    chart.legend.font.name, chart.legend.font.size = FONT, Pt(11)
                    chart.legend.font.color.rgb = rgb(MUTED)
                    value_axis, category_axis = chart.value_axis, chart.category_axis
                    value_axis.minimum_scale, value_axis.maximum_scale, value_axis.major_unit = low, high, step
                    value_axis.has_major_gridlines = True
                    value_axis.major_gridlines.format.line.color.rgb = rgb(LINE)
                    for ax in (value_axis, category_axis):
                        ax.tick_labels.font.name, ax.tick_labels.font.size = FONT, Pt(11)
                        ax.tick_labels.font.color.rgb = rgb(MUTED)
                        ax.major_tick_mark, ax.minor_tick_mark = XL_TICK_MARK.NONE, XL_TICK_MARK.NONE
                        ax.format.line.fill.background()
                    value_axis.tick_labels.number_format = '#,##0.#####'
                    for si, series in enumerate(chart.series):
                        color = (TEAL, COPPER)[si]
                        if block['kind'] == 'line':
                            series.format.line.color.rgb = rgb(color)
                            series.format.line.width = Pt(2.7)
                            series.smooth = False
                            series.marker.style, series.marker.size = XL_MARKER_STYLE.CIRCLE, 7
                            series.marker.format.fill.solid()
                            series.marker.format.fill.fore_color.rgb = rgb(WHITE)
                            series.marker.format.line.color.rgb = rgb(color)
                        else:
                            series.format.fill.solid()
                            series.format.fill.fore_color.rgb = rgb(color)
                            series.format.line.fill.background()
                    plot = chart.plots[0]
                    if len(block['categories']) <= 6 and len(block['series']) == 1:
                        plot.has_data_labels = True
                        labels = plot.data_labels
                        labels.position = XL_LABEL_POSITION.ABOVE if block['kind'] == 'line' else XL_LABEL_POSITION.OUTSIDE_END
                        labels.font.name, labels.font.size = FONT, Pt(11)
                        labels.font.color.rgb = rgb(INK)
                        labels.number_format = '#,##0.#####'
                elif kind == 'process':
                    n = len(block['steps'])
                    w = (12.03 - .32 * (n - 1)) / n
                    for k, item in enumerate(block['steps']):
                        x = .65 + k * (w + .32)
                        rect(slide, x, 2.3, w, 3.53)
                        box(slide, f'{k + 1:02d}', x + .23, 2.58, w - .46, .36, 13, TEAL, True)
                        box(slide, item['title'], x + .23, 3.15, w - .46, .75, 17, INK, True)
                        box(slide, item['text'], x + .23, 3.98, w - .46, 1.58, 15, MUTED)
                        if k < n - 1:
                            box(slide, '→', x + w + .025, 3.7, .28, .45, 20, TEAL)
                elif kind == 'matrix':
                    items = block['items']
                    for k, item in enumerate(items):
                        x, y = .65 + (k % 2) * 6.12, 2.0 + (k // 2) * 2.18
                        h = 4.15 if len(items) == 2 else 2.04
                        rect(slide, x, y, 5.91, h)
                        rect(slide, x + .23, y + .25, .035, .32, TEAL, None, False)
                        box(slide, item['title'], x + .4, y + .22, 5.2, .65, 17, INK, True)
                        box(slide, item['text'], x + .27, y + .83, 5.35, h - .97, 15, MUTED)
                elif kind == 'table':
                    rows = [block['headers']] + block['rows']
                    n = len(rows[0])
                    heights = [TABLE_ROW_BASE + TABLE_ROW_LINE * max(len(wrap(v, TABLE_COLUMNS / n)) for v in row) for row in rows]
                    table = slide.shapes.add_table(len(rows), n, Inches(.65), Inches(2.0), Inches(12.03), Inches(sum(heights))).table
                    table.first_row, table.horz_banding = True, False
                    for r, values in enumerate(rows):
                        table.rows[r].height = Inches(heights[r])
                        for c, value in enumerate(values):
                            cell = table.cell(r, c)
                            cell.text = '\n'.join(wrap(value, TABLE_COLUMNS / n))
                            cell.margin_left = cell.margin_right = Inches(.13)
                            cell.margin_top = cell.margin_bottom = Inches(.06)
                            cell.fill.solid()
                            cell.fill.fore_color.rgb = rgb(INK if r == 0 else WHITE if r % 2 else SOFT)
                            for p in cell.text_frame.paragraphs:
                                style(p, TABLE_FONT_SIZE, WHITE if r == 0 else INK, r == 0)
                else:
                    two = page['layout'] == 'two_column'
                    x, w, cols = (.65 + j * 6.12, 5.91, 16) if two else (.65, 12.03, 35)
                    texts = block['items'] if kind == 'bullets' else [block['text']]
                    heading = block.get('heading', '')
                    if two:
                        rect(slide, x, 2.03, w, 4.35, INK if j == 0 else WHITE)
                        color = 'D0DDDC' if j == 0 else MUTED
                        if heading:
                            box(slide, heading, x + .28, 2.28, w - .56, .6, 18, WHITE if j == 0 else INK, True)
                        text = '\n\n'.join(('• ' if kind == 'bullets' else '') + '\n'.join(wrap(t, cols)) for t in texts)
                        box(slide, text, x + .28, 3.03 if heading else 2.38, w - .56, 3.0 if heading else 3.6, 18, color, columns=cols + 2)
                    else:
                        # Variable-height rows preserve long legacy content without tiny fonts.
                        heights = [(len(wrap(t, 35)) * .35 + .24) for t in texts]
                        gap = min(.18, max(0, (4.35 - sum(heights)) / max(len(texts), 1)))
                        y = 2.0
                        for k, (text, h) in enumerate(zip(texts, heights)):
                            rect(slide, x, y, w, h)
                            box(slide, f'{k + 1:02d}', x + .2, y + .12, .5, .3, 12, TEAL, True)
                            box(slide, text, x + .83, y + .1, w - 1.06, h - .12, 20, INK, columns=35)
                            y += h + gap
            if page.get('caption'):
                box(slide, page['caption'], .68, 6.5, 11.9, .43, 10, MUTED, columns=78)
        rect(slide, .65, 7.05, 12.03, .009, '42616A' if cover else LINE, None, False)
        color = 'AAC4C5' if cover else MUTED
        box(slide, '大宗商品研究 · 分析演示', .65, 7.16, 10, .2, 9, color)
        box(slide, f'{i + 1:02d} / {len(pages):02d}', 11.9, 7.16, .8, .2, 9, color)
        slide.notes_slide.notes_text_frame.text = page['speaker_notes']
    prs.save(output)


def verify(output: Path, expected_pages: int):
    from pptx import Presentation
    from zipfile import ZipFile
    with ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError('Corrupt PPTX')
    prs = Presentation(output)
    if len(prs.slides) != expected_pages:
        raise ValueError('PPTX page count mismatch')
    for slide in prs.slides:
        if any(s.left < 0 or s.top < 0 or s.left + s.width > prs.slide_width + 1 or s.top + s.height > prs.slide_height + 1 for s in slide.shapes):
            raise ValueError('PPTX shape outside slide')
