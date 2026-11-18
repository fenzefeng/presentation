"""Deterministic, self-contained HTML research page."""
from __future__ import annotations

import base64
from datetime import date, timedelta
import hashlib
from html import escape
import json

from .contracts import ROOT, PresentationError, checked_research
from .render_html import render


def previous_week(day):
    return (date.fromisoformat(day) - timedelta(days=7)).isoformat() if day >= '0001-01-08' else ''


def signed(value):
    return f'{value:+,.4f}'.rstrip('0').rstrip('.') if value else '0'


def indicator_card(item):
    points = dict(item['points'])
    day, value = item['points'][-1]
    prior = points.get(previous_week(day))
    change = f"{signed(value - prior)} {escape(item['unit'])}" if prior is not None else '—'
    return (
        f'<article class="indicator"><h3><a href="#source-{item["source_id"]}">{escape(item["name"])}</a></h3>'
        f'<p class="value">{value:,} <small>{escape(item["unit"])}</small></p>'
        f'<p class="card-meta"><time datetime="{day}">{day}</time><span>周变化 {change}</span></p></article>'
    )


def raw_table(item):
    rows = ''.join(
        f'<tr><td><time datetime="{day}">{day}</time></td><td>{value:,}</td></tr>'
        for day, value in reversed(item['points'])
    )
    return (
        '<div class="table-scroll"><table>'
        f'<caption>{escape(item["name"])}</caption>'
        f'<thead><tr><th scope="col">日期</th><th scope="col">数值（{escape(item["unit"])}）</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div>'
    )


def source_details(source):
    description = source['description']
    try:
        meta = json.loads(description)
    except ValueError:
        meta = None
    if isinstance(meta, dict):
        labels = {'index_code': '指标编码', 'unit': '单位', 'frequency': '频率', 'period': '来源记录区间',
                  'observations_from': '观测取自'}
        parts = []
        for key, label in labels.items():
            value = meta.get(key)
            if isinstance(value, list):
                value = ' 至 '.join(map(str, value))
            if isinstance(value, str) and value.strip():
                parts.append(f'{label} {value}')
        description = ' · '.join(parts) or description
    source_id = source['id']
    href = source.get('url')
    link = f'<a href="{escape(href)}" target="_blank" rel="noopener noreferrer">{escape(href)}</a>' if href else ''
    day = source.get('data_date')
    return (f'<li id="source-{source_id}"><strong>[{source_id}] {escape(source["title"])}</strong>'
            + (f'<p>{escape(description)}</p>' if description else '')
            + (f'<p>数据日期 <time datetime="{day}">{day}</time></p>' if day else '') + link + '</li>')


def document(request, content):
    content = checked_research(request, content)
    title = escape(request.get('title') or content['title'])
    sources = {source['id']: source for source in request['sources']}
    series = {item['source_id']: dict(item, name=sources[item['source_id']]['title'])
              for item in request.get('series', [])}
    chosen = content.get('focus_ids') or list(series)[:2]
    ordered = [series[sid] for sid in dict.fromkeys([*chosen, *series])]
    dates = [item['points'][-1][0] for item in ordered] or [
        source['data_date'] for source in sources.values() if source.get('data_date')]
    metadata = [f'已收录数据截至 <time datetime="{max(dates)}">{max(dates)}</time>' if dates else '数据截止日期未标注']
    frequencies = list(dict.fromkeys(item['frequency'] for item in ordered if item.get('frequency')))
    if frequencies:
        metadata.append('频率 ' + escape('、'.join(frequencies)))
    metadata.append(f'<a href="#sources">来源 {len(sources)} 项</a>' if sources else '未提供数据来源')
    cards = ''.join(map(indicator_card, ordered[:len(chosen)]))
    options = ''.join(f'<option value="{sid}"{" selected" if sid in chosen else ""}>{escape(item["name"])}</option>'
                      for sid, item in series.items())
    controls = f"""
      <section class="trends" aria-labelledby="trends-title">
        <h2 id="trends-title">指标趋势</h2>
        <div id="research-controls" class="controls" hidden>
          <details class="metric-picker">
            <summary id="metric-summary">选择指标</summary>
            <div id="metric-options"></div>
          </details>
          <label>时间范围
            <select id="range"><option value="all">全部</option><option value="84">近 12 周</option><option value="28">近 4 周</option></select>
          </label>
          <label>显示方式
            <select id="mode"><option value="absolute">绝对值</option><option value="rate">周变化率</option><option value="index">基期指数</option></select>
          </label>
          <label>查看
            <select id="view"><option value="chart">图表</option><option value="table">明细</option></select>
          </label>
        </div>
        <select id="metric-data" multiple hidden>{options}</select>
        <p id="chart-note" class="meta" aria-live="polite">可展开下方数据明细查看原始观测值。</p>
        <div id="charts"></div>
      </section>""" if series else (
        '<p class="empty">材料未记录带日期、数值和单位的观测序列。可查看下方解读和来源。</p>'
    )
    insights = ''
    for item in content['insights']:
        citations = ' '.join(f'<a href="#source-{sid}">[{sid}]</a>' for sid in item.get('source_ids', []))
        insights += f'<article><h3>{escape(item["heading"])}</h3><p>{escape(item["text"])}</p>{citations}</article>'
    interpretation = f'<section class="insights"><h2>关键解读</h2>{insights}</section>' if insights else ''
    tables = ''.join(map(raw_table, ordered))
    data_details = f'<details id="data-details"><summary>数据明细</summary>{tables}</details>' if tables else ''
    source_items = ''.join(map(source_details, sources.values()))
    source_body = f'<ul>{source_items}</ul>' if source_items else '<p>未提供数据来源。</p>'
    data = escape(json.dumps(ordered, ensure_ascii=False, allow_nan=False))
    style = (ROOT / 'visuals/research.css').read_text(encoding='utf-8')
    script = (ROOT / 'visuals/research.js').read_text(encoding='utf-8')
    script_source = "'none'"
    runtime = ''
    if ordered:
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        script_source = f"'sha256-{digest}'"
        runtime = f'<script id="research-runtime">{script}</script>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src {script_source}; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{title}</title><style>{style}</style>
</head>
<body><div class="container"><main class="report">
<header><p class="topic">{title}</p><h1>{escape(content['conclusion'])}</h1>
<p class="meta">{' · '.join(metadata)}</p></header>
{f'<section class="indicators" aria-label="关键指标">{cards}</section>' if cards else ''}
{controls}
{interpretation}
<div class="details-grid">{data_details}<details id="sources"><summary>指标口径与来源</summary>{source_body}</details></div>
</main></div>
<template id="research-data">{data}</template>
{runtime}
</body></html>
"""


def verify(output, expected_pages):
    content = output.read_text(encoding='utf-8')
    if expected_pages != 0 or not content.startswith('<!doctype html>') or '<main class="report">' not in content:
        raise PresentationError('invalid_html', '研究文档不完整')
