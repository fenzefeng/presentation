(() => {
  'use strict';

  const series = JSON.parse(document.getElementById('research-data').content.textContent);
  const charts = document.getElementById('charts');
  const range = document.getElementById('range');
  const mode = document.getElementById('mode');
  const view = document.getElementById('view');
  const note = document.getElementById('chart-note');
  const metrics = document.getElementById('metric-options');
  const metricSummary = document.getElementById('metric-summary');
  const reportContainer = document.querySelector('.container');
  const detailSections = document.querySelectorAll('.details-grid > details');
  const selected = new Set(Array.from(document.getElementById('metric-data').selectedOptions, option => option.value));
  const DAY = 86400000;
  const round = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 });
  const compact = new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 2 });
  const signed = value => value > 0 ? '+' + round.format(value) : round.format(value);
  const iso = timestamp => new Date(timestamp).toISOString().slice(0, 10);
  const svgNS = 'http://www.w3.org/2000/svg';

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function svgElement(tag, attrs, text) {
    const node = document.createElementNS(svgNS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    return node;
  }

  for (const item of series) {
    item.byTime = new Map(item.points.map(([date, value]) => [Date.parse(date), value]));
    const label = element('label');
    const input = element('input');
    input.type = 'checkbox';
    input.checked = selected.has(item.source_id);
    input.addEventListener('change', () => {
      if (input.checked) selected.add(item.source_id);
      else selected.delete(item.source_id);
      refresh();
    });
    label.append(input, document.createTextNode(item.name));
    metrics.append(label);
  }

  function change(item, time, raw) {
    const prior = item.byTime.get(time - 7 * DAY);
    return {
      delta: prior === undefined ? null : raw - prior,
      rate: prior > 0 ? (raw / prior - 1) * 100 : null
    };
  }

  function chart(item, points, from, to, unit, bounds) {
    const figure = element('figure');
    const caption = element('figcaption', item.name + '（' + unit + '）');
    figure.append(caption);
    const visible = points.filter(point => point.value !== null);
    if (!visible.length) {
      figure.append(element('p', '所选区间缺少可用于该显示方式的观测值。', 'meta'));
      return figure;
    }
    const width = Math.max(150, charts.clientWidth);
    const height = parseFloat(getComputedStyle(charts).getPropertyValue('--plot-height'));
    const left = 60, right = width - 10, top = 10, bottom = height - 24;
    const values = visible.map(point => point.value);
    const [low, high] = bounds || [Math.min(...values), Math.max(...values)];
    const padding = low === high ? Math.abs(low) * 0.05 || 1 : (high - low) * 0.08;
    const x = time => from === to ? (left + right) / 2 : left + (time - from) / (to - from) * (right - left);
    const y = value => bottom - (value - low + padding) / (high - low + 2 * padding) * (bottom - top);
    const plot = svgElement('svg', {
      class: 'plot', viewBox: '0 0 ' + width + ' ' + height, preserveAspectRatio: 'none',
      role: 'group', tabindex: '0', 'aria-label': item.name + '趋势，使用左右方向键查看观测值'
    });
    for (const tick of low === high ? [low] : [high, low + (high - low) / 2, low]) {
      plot.append(
        svgElement('line', { class: 'axis', x1: left, x2: right, y1: y(tick), y2: y(tick) }),
        svgElement('text', { class: 'axis-label', x: left - 5, y: y(tick) + 3, 'text-anchor': 'end' },
          Math.abs(tick) >= 1e7 ? compact.format(tick) : round.format(tick))
      );
    }
    const ticks = from === to ? [from] : [from, ...(width >= 430 && to - from >= 2 * DAY ? [from + Math.round((to - from) / (2 * DAY)) * DAY] : []), to];
    for (const tick of ticks) {
      const anchor = from === to ? 'middle' : tick === from ? 'start' : tick === to ? 'end' : 'middle';
      plot.append(svgElement('text', { class: 'axis-label', x: x(tick), y: bottom + 19, 'text-anchor': anchor }, iso(tick)));
    }
    let path = '', previous = null;
    for (const point of points) {
      if (point.value === null) {
        previous = null;
        continue;
      }
      const weeklyGap = /周|week/i.test(item.frequency || '') && previous && point.time - previous.time > 7 * DAY;
      path += (previous && !weeklyGap ? 'L' : 'M') + x(point.time) + ',' + y(point.value);
      previous = point;
    }
    plot.append(svgElement('path', { class: 'trace', d: path }));
    for (const point of visible.length <= 30 ? visible : []) {
      plot.append(svgElement('circle', { cx: x(point.time), cy: y(point.value), r: '2.8' }));
    }
    const cursor = svgElement('line', { class: 'cursor', y1: top, y2: bottom });
    const marker = svgElement('circle', { r: '4' });
    plot.append(cursor, marker);
    const readout = element('p', '', 'readout');
    readout.setAttribute('aria-live', 'polite');
    let active = -1;

    function show(index) {
      if (active === index) return;
      active = index;
      const point = visible[index];
      const position = x(point.time);
      cursor.setAttribute('x1', position);
      cursor.setAttribute('x2', position);
      marker.setAttribute('cx', position);
      marker.setAttribute('cy', y(point.value));
      const parts = [point.date, String(point.raw) + ' ' + item.unit,
        '周变化 ' + (point.delta === null ? '—' : signed(point.delta) + ' ' + item.unit)];
      if (point.rate !== null) parts.push('周变化率 ' + signed(point.rate) + '%');
      if (mode.value === 'index') parts.push('基期指数 ' + round.format(point.value));
      readout.textContent = parts.join(' · ');
    }

    function showNearest(event) {
      const rect = plot.getBoundingClientRect();
      const position = (event.clientX - rect.left) * width / rect.width;
      let nearest = 0;
      for (let i = 1; i < visible.length; i++) {
        if (Math.abs(position - x(visible[i].time)) < Math.abs(position - x(visible[nearest].time))) nearest = i;
      }
      show(nearest);
    }
    plot.addEventListener('pointermove', showNearest);
    plot.addEventListener('pointerdown', showNearest);
    plot.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = { ArrowLeft: active - 1, ArrowRight: active + 1, Home: 0, End: visible.length - 1 }[event.key];
      show(Math.max(0, Math.min(next, visible.length - 1)));
    });
    show(visible.length - 1);
    figure.append(plot, readout);
    return figure;
  }

  function table(item, points, display, unit) {
    if (!points.length) return element('p', item.name + '：所选区间无观测值。', 'meta');
    const wrapper = element('div', undefined, 'table-scroll');
    const result = element('table');
    result.createCaption().textContent = item.name;
    const headers = ['日期', '原始值（' + item.unit + '）', '周变化（' + item.unit + '）'];
    if (display !== 'absolute') headers.push(unit);
    const heading = result.createTHead().insertRow();
    for (const label of headers) {
      const cell = element('th', label);
      cell.scope = 'col';
      heading.append(cell);
    }
    const tbody = result.createTBody();
    for (const point of points.slice().reverse()) {
      const row = tbody.insertRow();
      const cells = [point.date, String(point.raw), point.delta === null ? '—' : signed(point.delta)];
      if (display !== 'absolute') cells.push(point.value === null ? '—' : round.format(point.value));
      for (const text of cells) row.insertCell().textContent = text;
    }
    wrapper.append(result);
    return wrapper;
  }

  function refresh() {
    const items = series.filter(item => selected.has(item.source_id));
    const display = mode.value;
    metricSummary.textContent = '指标（' + items.length + '）';
    charts.replaceChildren();
    if (!items.length) {
      note.textContent = '请选择至少一项指标。';
      return;
    }
    const dates = items.flatMap(item => [...item.byTime.keys()]);
    const first = Math.min(...dates), to = Math.max(...dates);
    const from = range.value === 'all' ? first : Math.max(first, to - Number(range.value) * DAY);
    const base = display === 'index' ? [...items[0].byTime.keys()].find(time =>
      time >= from && items.every(item => item.byTime.get(time) > 0)) : undefined;
    const messages = {
      absolute: '各指标使用独立纵轴，日期对齐。周变化对比七天前的同指标观测值。',
      rate: '周变化率对比七天前的同指标观测值，缺值或基数非正时留空。',
      index: base === undefined ? '所选指标在此区间没有共同的正值观测日，无法计算基期指数。'
        : '共同基期 ' + iso(base) + ' = 100，采用同一纵轴尺度。'
    };
    note.textContent = messages[display];
    if (display === 'index' && base === undefined && view.value === 'chart') return;

    const datasets = items.map(item => ({
      item,
      unit: display === 'absolute' ? item.unit : display === 'rate' ? '周变化率（%）' : '基期指数',
      points: item.points.map(([date, raw]) => {
        const time = Date.parse(date), { delta, rate } = change(item, time, raw);
        const value = display === 'absolute' ? raw : display === 'rate' ? rate
          : base === undefined || time < base ? null : raw / item.byTime.get(base) * 100;
        return { date, time, raw, delta, rate, value: Number.isFinite(value) ? value : null };
      }).filter(point => point.time >= from)
    }));
    const values = display === 'index' ? datasets.flatMap(data =>
      data.points.filter(point => point.value !== null).map(point => point.value)) : [];
    const bounds = values.length ? [Math.min(...values), Math.max(...values)] : null;
    for (const { item, unit, points } of datasets) {
      charts.append(view.value === 'chart' ? chart(item, points, from, to, unit, bounds) : table(item, points, display, unit));
    }
  }

  for (const select of [range, mode, view]) select.addEventListener('change', refresh);
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href^="#source"]');
    if (link) document.getElementById('sources').open = true;
  });
  let lastWidth = charts.clientWidth;
  let wide = false;
  new ResizeObserver(() => {
    const nextWide = reportContainer.clientWidth >= 880;
    if (nextWide && !wide) {
      for (const section of detailSections) section.open = true;
    }
    wide = nextWide;
    const width = charts.clientWidth;
    if (width !== lastWidth) {
      lastWidth = width;
      refresh();
    }
  }).observe(charts);
  document.getElementById('research-controls').hidden = false;
  refresh();
})();
