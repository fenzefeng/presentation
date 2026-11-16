import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import copy
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from presentation_core import generate, render
from presentation_core.contracts import ROOT, PresentationError, normalize_request, validate


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {'output_root': self.temp.name}
        self.request = json.loads((ROOT / 'examples/request.json').read_text())
        self.deck = json.loads((ROOT / 'examples/deck.json').read_text())
        self.html = (ROOT / 'examples/presentation.html').read_text()

    def test_model_html_is_preserved_and_manifest_matches(self):
        result = render(self.request, self.html, config=self.config)
        self.assertEqual(result['status'], 'succeeded')
        validate('result', result)
        file = Path(result['artifacts'][0]['local_path'])
        data = file.read_bytes()
        self.assertIn(b'<script>', data)
        self.assertIn(b"document.querySelectorAll('.slide')", data)
        self.assertIn(b'Content-Security-Policy', data)
        self.assertFalse((file.parent / 'deck.json').exists())
        self.assertEqual(result['artifacts'][0]['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(result['artifacts'][0]['size_bytes'], len(data))
        self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(Path(self.temp.name).glob('.*.tmp')))

    def test_native_pptx_has_editable_text_and_notes(self):
        from pptx import Presentation
        self.request['target_format'] = 'pptx'
        result = render(self.request, self.deck, config=self.config)
        self.assertEqual(result['status'], 'succeeded')
        prs = Presentation(result['artifacts'][0]['local_path'])
        self.assertEqual(len(prs.slides), 3)
        self.assertIn('供应', '\n'.join(s.text for s in prs.slides[1].shapes if s.has_text_frame))
        self.assertEqual(prs.slides[1].notes_slide.notes_text_frame.text, self.deck['slides'][0]['speaker_notes'])

    def test_table_and_two_column_work_in_pptx(self):
        self.deck['slides'].extend([
            {'layout': 'two_column', 'title': '观察与限制', 'speaker_notes': '', 'blocks': [
                {'type': 'paragraph', 'text': '供应与需求应结合观察。'},
                {'type': 'bullets', 'items': ['不提供量化预测。']}]},
            {'layout': 'table', 'title': '结论整理', 'speaker_notes': '', 'blocks': [
                {'type': 'table', 'headers': ['维度', '说明'], 'rows': [['数据', '缺少可比较的数据序列']]}]}])
        self.request['target_format'] = 'pptx'
        result = render(self.request, self.deck, config=self.config)
        self.assertEqual(result['status'], 'succeeded', result.get('error'))
        self.assertEqual(result['slide_count'], 5)

    def test_five_column_table_is_supported(self):
        self.deck['slides'].append({
            'layout': 'table', 'title': '五列表', 'speaker_notes': '', 'blocks': [{
                'type': 'table', 'headers': ['指标', '编码', '首值', '末值', '变化'],
                'rows': [['供应', '需求', '库存', '价格', '发运']]}]})
        self.request['target_format'] = 'pptx'
        result = render(self.request, self.deck, config=self.config)
        self.assertEqual(result['status'], 'succeeded', result.get('error'))

    def test_dense_five_column_table_fits_table_area(self):
        cell = '供应与需求指标需要结合观察并核对口径'
        self.deck['slides'].append({
            'layout': 'table', 'title': '密集表', 'speaker_notes': '', 'blocks': [{
                'type': 'table', 'headers': ['指标', '编码', '首值', '末值', '变化'],
                'rows': [[cell, '编码甲乙丙丁', cell, cell, cell] for _ in range(4)]}]})
        self.request['target_format'] = 'pptx'
        result = render(self.request, self.deck, config=self.config)
        self.assertEqual(result['status'], 'succeeded', result.get('error'))

    def test_block_number_may_come_from_another_analysis_section(self):
        request = {'schema_version': '1.0', 'analysis': '库存增加 10。需求下降 5。',
                   'sources': [{'id': 's1', 'title': '来源', 'description': '说明'}],
                   'target_format': 'pptx', 'max_slides': 5}
        deck = {'schema_version': '1.0', 'title': '测试', 'slides': [{
            'layout': 'bullets', 'title': '需求', 'speaker_notes': '',
            'blocks': [{'type': 'bullets', 'items': ['需求下降 5']}]}]}
        result = render(request, deck, config=self.config)
        self.assertEqual(result['status'], 'succeeded', result.get('error'))

    def test_legacy_evidence_fields_do_not_block_rendering(self):
        self.request['target_format'] = 'pptx'
        for field, value in [('source_ids', ['nonexistent']), ('evidence_quote', '不在原文')]:
            with self.subTest(field=field):
                deck = copy.deepcopy(self.deck)
                deck['slides'][0]['blocks'][0][field] = value
                result = render(self.request, deck, config=self.config)
                self.assertEqual(result['status'], 'succeeded')

    def test_number_matching_is_not_a_generation_gate(self):
        self.request['target_format'] = 'pptx'
        self.deck['slides'][0]['blocks'][0]['items'][0] = '价格上涨20%'
        result = render(self.request, self.deck, config=self.config)
        self.assertEqual(result['status'], 'succeeded')


    def test_duplicate_sources_and_blank_analysis_rejected_before_planning(self):
        for field, value in [('analysis', '  '), ('sources', self.request['sources'] * 2)]:
            with self.subTest(field=field), self.assertRaises(PresentationError):
                normalize_request({**self.request, field: value})

    def test_missing_sources_warns(self):
        self.request['sources'] = []
        html = self.html.replace('[s1] 合成分析材料', '未提供数据来源')
        result = render(self.request, html, config=self.config)
        self.assertIn('sources_missing', result['warnings'])
        self.assertIn('未提供数据来源', Path(result['artifacts'][0]['local_path']).read_text())

    def test_cancelled_generation_has_no_artifact(self):
        event = threading.Event()
        event.set()
        result = render(self.request, self.html, config=self.config, cancel=event)
        self.assertEqual(result['status'], 'cancelled')
        validate('result', result)

    def test_renderer_failure_cleans_partial_file(self):
        def broken(pages, output):
            output.write_text('incomplete')
            raise ValueError('private upstream response must not leak')
        with patch('presentation_core.render_html.render', side_effect=broken):
            result = render(self.request, self.html, config=self.config)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('private upstream', json.dumps(result))
        self.assertFalse(list((Path(self.temp.name) / result['generation_id']).glob('presentation.*')))

    def test_injected_planner_runs_whole_pipeline(self):
        html = self.html
        class FakePlanner:
            def plan(self, request, *, deadline, cancel):
                return html
        result = generate(self.request, config=self.config, planner=FakePlanner())
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['provenance']['mode'], 'model')

    def test_overflow_rejected(self):
        self.request['target_format'] = 'pptx'
        self.deck['slides'] *= 7
        result = render(self.request, self.deck, config=self.config)
        self.assertEqual(result['error']['code'], 'layout_overflow')

    def test_symlink_output_root_rejected(self):
        link = Path(self.temp.name) / 'link'
        link.symlink_to(self.temp.name)
        with self.assertRaises(PresentationError):
            render(self.request, self.html, config={'output_root': str(link)})

    def test_html_fence_is_removed_and_source_rewording_is_allowed(self):
        result = render(self.request, '```html\n' + self.html + '\n```', config=self.config)
        self.assertEqual(result['status'], 'succeeded')
        self.assertTrue(Path(result['artifacts'][0]['local_path']).read_text().startswith('<!doctype html>'))
        result = render(self.request, self.html.replace('合成分析材料', '来源遗漏'), config=self.config)
        self.assertEqual(result['status'], 'succeeded')

    def test_truncated_html_is_not_published(self):
        result = render(self.request, self.html.split('</body>')[0], config=self.config)
        self.assertEqual(result['error']['code'], 'invalid_html')
        self.assertEqual(result['artifacts'], [])

    def test_complete_document_allows_script_after_body_and_bom(self):
        html = '\ufeff' + self.html.replace('</body>\n</html>', '</body>\n<script>void 0;</script>\n</html>')
        result = render(self.request, html, config=self.config)
        self.assertEqual(result['status'], 'succeeded')

    def test_html_does_not_accept_deck_input(self):
        result = render(self.request, self.deck, config=self.config)
        self.assertEqual(result['error']['code'], 'invalid_html')


if __name__ == '__main__':
    unittest.main()
