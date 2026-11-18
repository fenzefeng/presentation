"""Model-facing presentation skill over trusted per-task history and evidence."""
import hashlib
import json
import threading
from pathlib import Path

from .agent import AgentPresentation, snapshot

SKILL_DIR = Path(__file__).resolve().parents[2]


class PresentationSkill(AgentPresentation):
    def __init__(self, context, session, evidence, **kwargs):
        super().__init__(context, session, **kwargs)
        self.evidence = evidence
        self.selected_ids = []
        self.selection_lock = threading.Lock()
        self.materials = list(context.get('materials') or [])
        if not self.materials and context.get('analysis'):
            self.materials = [context['analysis']]

    def history(self, message_ids):
        if not isinstance(message_ids, list) or len(message_ids) > 20:
            return {'status': 'failed', 'error': 'invalid_material_selection'}
        self.session.event('raw_tool_call', tool='presentation_history', message_ids=message_ids)
        if not message_ids:
            return {'materials': [{'message_id': m['message_id'], 'preview': m['analysis'][:600],
                                  'sources': len(m['sources'])} for m in self.materials],
                    'history_truncated': bool(self.context.get('history_truncated')),
                    'history_error': self.context.get('history_error')}
        by_id = {m['message_id']: m for m in self.materials}
        if any(mid not in by_id for mid in message_ids):
            return {'status': 'failed', 'error': 'analysis_not_available'}
        selected = [by_id[mid] for mid in message_ids]
        # Bound an individual observation without silently truncating a material.
        summaries = [{k: v for k, v in material.items() if k != 'series'} for material in selected]
        if len(json.dumps(summaries, ensure_ascii=False)) > 14000:
            return {'status': 'failed', 'error': 'read_fewer_messages'}
        return {'materials': summaries}

    def generate(self, analysis_message_ids, target_format, analysis_text=''):
        with self.selection_lock:
            return self._generate(analysis_message_ids, target_format, analysis_text)

    def _generate(self, analysis_message_ids, target_format, analysis_text=''):
        if not isinstance(analysis_message_ids, list) or len(analysis_message_ids) > 20 or len(set(analysis_message_ids)) != len(analysis_message_ids):
            return {'status': 'failed', 'error': 'invalid_material_selection'}
        if not isinstance(analysis_text, str) or len(analysis_text) > 24000:
            return {'status': 'failed', 'error': 'invalid_analysis'}
        if self.context.get('phase') == 'presentation' and analysis_text.strip():
            return {'status': 'failed', 'error': 'analysis_is_read_only'}
        if self.context.get('phase') == 'presentation' and target_format != self.context.get('target_format'):
            return {'status': 'failed', 'error': 'format_mismatch'}
        by_id = {m['message_id']: m for m in self.materials}
        if any(mid not in by_id for mid in analysis_message_ids):
            return {'status': 'failed', 'error': 'analysis_not_available'}
        selected = [m for m in self.materials if m['message_id'] in analysis_message_ids]
        if analysis_text.strip():
            evidence = dict(self.evidence(), answer=analysis_text, answer_complete=True)
            current = snapshot('cm_current_' + str(self.context['run_id']), evidence)
            if current is None:
                return {'status': 'failed', 'error': 'analysis_not_usable'}
            selected.append(current)
        if not selected:
            return {'status': 'failed', 'error': 'analysis_required'}
        sources, bodies, series = [], [], []
        for index, material in enumerate(selected, 1):
            body = material['analysis']
            source_map = {}
            for source in material['sources']:
                identifier = 'M%d_%s' % (index, source['id'])
                if len(identifier) > 64:
                    identifier = 'M%d_%s' % (index, hashlib.sha256(source['id'].encode()).hexdigest()[:24])
                source_map[source['id']] = identifier
                body = body.replace('[' + source['id'] + ']', '[' + identifier + ']')
                sources.append(dict(source, id=identifier))
            series.extend(dict(item, source_id=source_map[item['source_id']]) for item in material.get('series', []))
            bodies.append('### 材料 %d\n%s' % (index, body))
        body = '\n\n'.join(bodies)
        if len(body) > 24000 or len(sources) > 30:
            return {'status': 'failed', 'error': 'material_budget_exceeded',
                    'guidance': '请缩小消息范围，不能静默省略历史正文或来源。'}
        identity = hashlib.sha256(json.dumps([m['message_id'] for m in selected]).encode()).hexdigest()[:24]
        material = {'message_id': 'cm_selection_' + identity, 'analysis': body, 'sources': sources}
        if series:
            if len(series) > 12 or sum(len(item['points']) for item in series) > 1200:
                return {'status': 'failed', 'error': 'material_budget_exceeded',
                        'guidance': '观测点超出展示上限，请缩小消息范围。'}
            material['series'] = series
        # A changed selection after generation cannot publish a second file.
        if self.called and self.context.get('analysis') != material:
            return {'status': 'failed', 'error': 'presentation_limit'}
        self.context = dict(self.context, analysis=material, defer_until_analysis=False)
        self.selected_ids = [m['message_id'] for m in selected]
        result = self.create(material['message_id'], target_format)
        for artifact in self.artifacts:
            artifact['source_message_ids'] = self.selected_ids
        return result

    def answer(self, output):
        value = super().answer(output)
        value['presentation_execution'].update(skill='presentation', trigger='skill',
                                                source_message_ids=self.selected_ids)
        if self.context.get('analysis') and self.artifacts:
            value['presentation_material'] = self.context['analysis']
        return value
