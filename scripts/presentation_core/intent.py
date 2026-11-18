"""Lightweight routing hints; presentation material selection belongs to the skill."""
from __future__ import annotations

import re

_PRESENTATION = re.compile(r'(PPTX?|幻灯片|演示文稿|演示|HTML|网页|deck|slides?)', re.IGNORECASE)
_NEGATED = re.compile(r'(不|不要|不用|无需|别|取消|不需要).{0,8}(PPT|幻灯片|演示|HTML|网页)', re.IGNORECASE)
_PRIOR = re.compile(r'(刚才|刚刚|上文|上面|之前|此前|前面|这份|那份|该分析|以上分析|已有分析|前面的分析|上一轮)')
_ANALYSIS = re.compile(r'(分析|判断|评估|研究|解读|展望|预测|怎么看|如何看|为什么|报告|周报|日报|晨报|复盘)')
_TOPIC = re.compile(r'(铁矿石|铁矿|供需|供给|需求|走势|行情|市场|价格|库存|产量|发运|到港|疏港|开工|铁水|成本|利润|基本面)')


def presentation_target(question: str):
    """Return 'pptx' or 'html' only when the question actually asks for a deck."""
    text = question or ''
    if not _PRESENTATION.search(text) or _NEGATED.search(text):
        return None
    if re.search(r'(HTML|网页)', text, re.IGNORECASE):
        return 'html'
    if re.search(r'(PPTX?|幻灯片|演示文稿|powerpoint)', text, re.IGNORECASE):
        return 'pptx'
    return 'html'


def is_combined_request(question: str) -> bool:
    """Legacy classification helper; not used to orchestrate runtime generation."""
    text = question or ''
    if presentation_target(text) is None or _PRIOR.search(text):
        return False
    return bool(_ANALYSIS.search(text) and _TOPIC.search(text))


def presentation_request(question: str):
    """Project explicit display clauses out of the analysis request.

    No model is used here. Unknown mixtures are reported rather than silently
    forwarding slide/page instructions to Fusion's analysis router.
    """
    target = presentation_target(question)
    if target is None:
        return None
    text = (question or '').strip()
    generation = re.search(r'制作|生成|做成|做为|做个|做一|转为|转成|转换|整理|输出|给出|提供|想要|需要|演示一下|(?:用|以|采用).{0,12}(?:PPT|HTML|演示|幻灯片)', text, re.I)
    if generation is None and not re.fullmatch(r'(?:请)?\s*(?:\d+页)?\s*(?:PPTX?|HTML|幻灯片|演示)', text, re.I):
        return None
    count_match = re.search(r'(?<!第)(\d+|[一二三四五六七八九十两]+)\s*(?:页|张)', text)
    count = None
    if count_match:
        value = count_match[1]
        if value.isdigit():
            count = int(value)
        else:
            digits = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
                      '六': 6, '七': 7, '八': 8, '九': 9}
            if '十' in value:
                first, last = value.split('十', 1)
                count = digits.get(first, 1) * 10 + digits.get(last, 0)
            else:
                count = digits.get(value)
    fmt = r'(?:HTML|PPTX?|PowerPoint|幻灯片|演示文稿|演示|网页|slides?|deck)(?:演示|文稿|文件|页面)?'
    pages = r'(?:\d+|[一二三四五六七八九十两]+)\s*(?:页|张)\s*(?:的)?\s*'
    qualifier = r'(?:(?:中文|精美|简洁|离线|可下载|一个|一份|一套|一版|的)\s*)*'
    display = r'(?:' + pages + r')?' + qualifier + fmt + r'(?:\s*(?:的)?\s*' + pages + r')?'
    action = r'(?:制作|生成|做成|做为|做|输出|整理|转换|转|给出|提供)(?:成|为)?\s*'
    prefix = r'(?:[，,；;。]?\s*(?:并且|并|然后|最后|同时|顺便|再)\s*)?(?:请|帮我|给我)?\s*'
    analysis = re.sub(prefix + action + qualifier + display, '', text, flags=re.I)
    analysis = re.sub(r'(?:请)?(?:用|以|采用)\s*' + display + r'(?:来)?', '', analysis, flags=re.I)
    analysis = re.sub(r'^[，,；;。\s]+|[，,；;。\s]+$', '', analysis)
    # A reference to earlier analysis is material selection, not a new analysis.
    explicit_new = re.search(r'(?:^|[，,；;。]|根据[^。]{0,80})(?:请)?(?:再|重新|进一步)?(?:分析|判断|评估|研究|解读|展望|预测)\S', analysis)
    if (_PRIOR.search(analysis) and not explicit_new) or not _TOPIC.search(analysis):
        analysis = None
    if analysis is None and re.search(r'以下.*(?:分析|材料)', text) and re.search(r'[:：]', text):
        supplied = re.split(r'[:：]', text, maxsplit=1)[1].strip()
        if supplied:
            analysis = '请根据以下材料进行分析：' + supplied
    error = 'ambiguous_analysis_request' if analysis and _PRESENTATION.search(analysis) else None
    return {'target_format': target, 'analysis_question': analysis,
            'requested_slides': count if target == 'pptx' else None, 'error': error}
