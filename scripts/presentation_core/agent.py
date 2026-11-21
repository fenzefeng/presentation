"""Agent-facing adapter. Material and configuration come from the trusted host."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from .contracts import PresentationError, normalize_request
from .service import generate

# A combined answer keeps its analysis outcome while carrying an attachment;
# presentation_answer is the presentation-only result and must not be reused as analysis.
ANALYSIS_OUTCOMES = frozenset({'success', 'no_data', 'model_answer', 'reference_answer',
                               'calculation_answer', 'consultation_answer'})


def snapshot(message_id, result):
    """Project actual engine evidence into the presentation input contract."""
    answer = result.get('answer')
    if not isinstance(answer, str) or not answer.strip() or result.get('answer_complete') not in (True, 1):
        return None
    if result.get('artifacts') and result.get('outcome') not in ANALYSIS_OUTCOMES:
        return None  # Presentation-only history is not a new market analysis.
    if result.get('artifacts') and result.get('outcome') is None:
        return None  # Older presentation-only archives did not store an outcome.
    sources, series = [], []
    archived = result.get('presentation_series') or {}
    remaining = 1200
    for row in result.get('data_results') or result.get('data') or []:
        if not isinstance(row, dict):
            continue
        title = row.get('cn_name') or row.get('indicator_name') or row.get('name')
        if not title:
            continue
        description = {k: row[k] for k in ('index_code', 'unit', 'frequency', 'period', 'observations_from') if k in row}
        source_id = 'D' + str(len(sources) + 1)
        sources.append({'id': source_id, 'title': str(title)[:160],
                        'description': json.dumps(description, ensure_ascii=False)[:1200] or '指标工具返回的证据'})
        points = row.get('rows') or archived.get(row.get('handle'))
        unit = row.get('unit')
        if isinstance(points, (list, tuple)) and points and isinstance(unit, str) and unit.strip() and len(series) < 12 and remaining:
            try:
                item = {'source_id': source_id, 'unit': unit.strip()[:80],
                        'points': [list(point) for point in points[-remaining:]]}
                frequency = row.get('frequency')
                if isinstance(frequency, str) and frequency.strip():
                    item['frequency'] = frequency.strip()[:60]
                normalize_request({'schema_version': '1.0', 'analysis': '时序',
                                   'sources': [sources[-1]], 'target_format': 'html', 'series': [item]})
            except (PresentationError, TypeError):
                continue  # Keep the source if its historical rows cannot be plotted.
            series.append(item)
            remaining -= len(item['points'])
    for field, prefix in (('web_results', 'W'), ('rag_results', 'R')):
        source_number = 0
        for group in result.get(field) or []:
            if not isinstance(group, dict):
                continue
            for row in group.get('results') or group.get('rows') or []:
                if not isinstance(row, dict):
                    continue
                title = row.get('title') or row.get('document_id') or row.get('source_id') or '检索材料'
                description = row.get('content') or row.get('text') or row.get('snippet') or str(title)
                source_number += 1
                existing_id = row.get('source_id')
                source_id = (existing_id if isinstance(existing_id, str) and
                             re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', existing_id) else prefix + str(source_number))
                used_ids = {s['id'] for s in sources}
                while source_id in used_ids:
                    source_number += 1
                    source_id = prefix + str(source_number)
                source = {'id': source_id, 'title': str(title)[:160],
                          'description': str(description)[:1200]}
                url = row.get('url') or row.get('source_url')
                if isinstance(url, str) and re.match(r'^https?://\S+$', url):
                    source['url'] = url
                sources.append(source)
    # Do not silently drop evidence or truncate the original analysis.
    if len(sources) > 30 or len(answer) > 24000:
        return None
    material = {'message_id': message_id, 'analysis': answer, 'sources': sources}
    if series:
        material['series'] = series
    try:
        normalize_request({'schema_version': '1.0', 'analysis': answer, 'sources': sources, 'target_format': 'html'})
    except PresentationError:
        return None
    return material


class AgentPresentation:
    def __init__(self, context, session, generator=generate):
        self.context, self.session, self.generator = context, session, generator
        self.called = False
        self.artifacts = []
        self.result = None
        self.key = None
        self.error = None
        self.started = time.monotonic()
        self.lock = threading.Lock()

    def create(self, analysis_message_id: str, target_format: str) -> dict:
        with self.lock:
            return self._create(analysis_message_id, target_format)

    def _create(self, analysis_message_id, target_format):
        key = (analysis_message_id, target_format)
        if self.called:
            return self.result if key == self.key else {'status': 'failed', 'error': 'presentation_limit'}
        self.called, self.key = True, key
        self.session.event('raw_tool_call', tool='create_presentation', target_format=target_format)
        if self.context.get('defer_until_analysis'):
            self.error = 'deferred'
            self.result = {'status': 'failed', 'error': self.error}
            return self.result
        material = self.context.get('analysis')
        if target_format not in ('html', 'pptx'):
            self.error = 'invalid_format'
        elif not material:
            self.error = 'analysis_required'
        elif analysis_message_id not in ('latest', material['message_id']):
            self.error = 'analysis_not_available'
        if self.error:
            self.result = {'status': 'failed', 'error': self.error}
            return self.result
        try:
            config_path = Path(self.context['config_file'])
            if config_path.is_symlink() or config_path.stat().st_uid != os.getuid() or config_path.stat().st_mode & 0o077:
                raise PresentationError('invalid_request', '演示配置需要当前用户私有文件')
            config = json.loads(config_path.read_text())
            # One session charge; a failed structural/layout attempt may be
            # repaired once inside the same generation call.
            config['max_model_attempts'] = 2
            # Real analyses with many sources exceed the original 16 KB
            # conservative budget; the model context and the validated 32 KB
            # cap leave room for 24 KB.
            config['max_input_tokens'] = max(24000, config.get('max_input_tokens', 16000))
            timeout = self.context.get('total_timeout_seconds')
            if isinstance(timeout, int) and timeout > 0:
                config['total_timeout_seconds'] = max(
                    1, min(config.get('total_timeout_seconds', 180), 180, timeout))
                config['model_timeout_seconds'] = max(
                    1, min(config.get('model_timeout_seconds', 60), config['total_timeout_seconds']))
            else:
                config['total_timeout_seconds'] = min(config.get('total_timeout_seconds', 180), 180)
            try:
                max_slides = int(self.context.get('max_slides', 8))
            except (TypeError, ValueError):
                max_slides = 8
            request = {'schema_version': '1.0', 'analysis': material['analysis'],
                       'sources': material['sources'], 'target_format': target_format,
                       'max_slides': max(1, min(12, max_slides))}
            if material.get('series'):
                request['series'] = material['series']
            if target_format == 'pptx' and self.context.get('requested_slides') is not None:
                request['requested_slides'] = self.context['requested_slides']
                request['max_slides'] = self.context['requested_slides']
            outcome = self.session.call('model', lambda: self.generator(request, config=config))
            if outcome['status'] != 'succeeded':
                self.error = (outcome.get('error') or {}).get('code', 'presentation_failed')
            else:
                for file in outcome['artifacts']:
                    public = {k: file[k] for k in ('artifact_id', 'format', 'filename', 'media_type', 'size_bytes', 'sha256')}
                    public.update(generation_id=outcome['generation_id'], slide_count=outcome['slide_count'],
                                  source_message_id=material['message_id'])
                    self.artifacts.append(public)
        except Exception:
            self.error = 'presentation_failed'
        self.result = ({'status': 'succeeded', 'artifacts': self.artifacts} if self.artifacts else
                       {'status': 'failed', 'error': self.error or 'presentation_failed'})
        self.session.event('presentation_finished', status=self.result['status'], artifacts=len(self.artifacts))
        return self.result

    def answer(self, agent_output):
        success = bool(self.artifacts)
        answer = ('演示已生成，请打开返回的演示文件。' if success else
                  '演示未生成：' + ('当前没有可用的完整分析，请先完成分析。' if self.error == 'analysis_required'
                                  else '生成失败或目标分析不可用，请核对后重新提交。'))
        return {'runtime': 'QwenPawAgent', 'answer': answer, 'artifacts': self.artifacts,
                'answer_complete': success, 'answer_status': 'complete' if success else 'failed',
                'outcome': 'presentation_answer' if success else 'presentation_failed',
                'error': None if success else {'code': self.error or 'presentation_failed'},
                'presentation_execution': {'trigger': 'agent', 'tool': 'create_presentation',
                    'status': 'succeeded' if success else 'failed', 'target_format': self.key[1] if self.key else None,
                    'elapsed_seconds': round(time.monotonic() - self.started, 3), 'error': self.error},
                'session_id': self.session.id, 'reference_date': self.session.reference_date,
                'calls': self.session.counts(), 'limits': self.session.limits,
                'skill_trace': self.session.trace, 'data_results': [], 'web_results': [], 'rag_results': [],
                'full_api_chain': False, 'execution_mode': 'base_agent',
                'elapsed_seconds': round(time.monotonic() - self.started, 3)}


class CurrentResultSession:
    """Minimal ledger for a deck generated from this turn's completed result."""

    def __init__(self, result):
        self.id = str(result.get('session_id') or result.get('run_id') or 'current')
        self.reference_date = result.get('reference_date')
        self.limits = result.get('limits') or {}
        self.trace = list(result.get('skill_trace') or [])
        self.used = 0

    def event(self, name, **fields):
        self.trace.append({'event': name, 'origin': 'worker_hook', **fields})

    def call(self, stage, fn):
        self.used += 1
        return fn()

    def counts(self):
        return {'model': self.used}


def generate_current(result, *, config_file, run_id, target_format,
                     message_id=None, generator=generate, timeout_seconds=None, max_slides=None):
    """Host hook for a combined analysis+presentation request.

    Uses only this run's result, never user- or model-supplied analysis text.
    """
    if not isinstance(result, dict):
        return {'status': 'failed', 'error': 'analysis_unavailable'}
    try:
        material = snapshot(message_id or ('cm_current_' + str(run_id)), result)
    except Exception:
        material = None
    if material is None:
        return {'status': 'failed', 'error': 'analysis_unavailable'}
    context = {'config_file': config_file, 'run_id': run_id, 'analysis': material,
               'max_slides': max_slides}
    if isinstance(timeout_seconds, int) and timeout_seconds > 0:
        context['total_timeout_seconds'] = timeout_seconds
    tool = AgentPresentation(context, CurrentResultSession(result), generator=generator)
    generated = dict(tool.create('latest', target_format))
    generated['generation_calls'] = tool.session.used
    return generated


def attach_current(result, *, config_file, run_id, target_format,
                   timeout_seconds=None, max_slides=None, generator=generate):
    """Generate from this turn's result and merge the attachment into its answer."""
    started = time.monotonic()
    merged = dict(result) if isinstance(result, dict) else {}
    if not merged:
        return merged
    if isinstance(timeout_seconds, int) and timeout_seconds < 20:
        generated = {'status': 'failed', 'error': 'deadline_exceeded'}
    else:
        generated = generate_current(result, config_file=config_file, run_id=run_id,
                                     target_format=target_format, max_slides=max_slides,
                                     timeout_seconds=timeout_seconds, generator=generator)
    if generated.get('status') == 'succeeded' and generated.get('artifacts'):
        merged['artifacts'] = generated['artifacts']
        merged['answer'] = (merged.get('answer') or '').rstrip() + '\n\n已按本轮分析生成演示文件。'
    else:
        code = generated.get('error') or 'presentation_failed'
        note = ('本轮分析材料不完整或超限' if code == 'analysis_unavailable'
                else '任务剩余时间不足' if code == 'deadline_exceeded'
                else '演示生成失败')
        merged['answer'] = (merged.get('answer') or '').rstrip() + '\n\n演示未生成（' + note + '），分析正文已保留。'
    charge = generated.get('generation_calls', 1 if generated.get('status') == 'succeeded' else 0)
    counts = dict(merged.get('calls') or {})
    counts['model'] = counts.get('model', 0) + charge
    merged['calls'] = counts
    if isinstance(merged.get('actual_calls'), dict):
        merged['actual_calls'] = dict(merged['actual_calls'])
        merged['actual_calls']['model'] = merged['actual_calls'].get('model', 0) + charge
    merged['presentation_execution'] = {'trigger': 'host', 'tool': 'create_presentation',
        'status': generated.get('status'), 'target_format': target_format,
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'error': generated.get('error'), 'generation_calls': charge}
    return merged


def resolve_artifact(config_file, public):
    """Resolve only a server-owned manifest entry, never a client path."""
    import hashlib
    import uuid
    cfg = json.loads(Path(config_file).read_text())
    generation = str(uuid.UUID(public['generation_id']))
    artifact_id = str(uuid.UUID(public['artifact_id']))
    root = Path(cfg['output_root'])
    folder = root / generation
    if folder.is_symlink() or root.is_symlink():
        raise ValueError('unsafe_artifact')
    result = json.loads((folder / 'result.json').read_text())
    item = next(a for a in result['artifacts'] if a['artifact_id'] == artifact_id)
    if result['status'] != 'succeeded' or item['filename'] not in ('presentation.html', 'presentation.pptx'):
        raise ValueError('artifact_not_ready')
    path = folder / item['filename']
    if path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError('unsafe_artifact')
    data = path.read_bytes()
    if len(data) != item['size_bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
        raise ValueError('artifact_changed')
    return data, item['media_type'], item['filename']
