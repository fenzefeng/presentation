import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from presentation_core.contracts import ROOT, PresentationError
from presentation_core.model_worker import load_arm, plan
from presentation_core.service import configuration


class ModelWorkerTests(unittest.TestCase):
    def setUp(self):
        self.request = json.loads((ROOT / 'examples/request.json').read_text())
        self.request['target_format'] = 'pptx'
        self.deck = json.loads((ROOT / 'examples/deck.json').read_text())
        self.config = configuration()

    def test_html_model_output_is_structured_and_cannot_supply_observations(self):
        self.request = json.loads((ROOT / 'examples/research-request.json').read_text())
        research = (ROOT / 'examples/research.json').read_text()
        opener = Mock()
        opener.open.return_value = self.response(research)
        with patch('presentation_core.model_worker.load_arm', return_value=(
                {'url': 'https://example.invalid/chat/completions', 'model': 'dummy'}, 'test-secret')), \
                patch('presentation_core.model_worker.urllib.request.build_opener', return_value=opener):
            result = plan(self.request, self.config)
        self.assertEqual(result, json.loads(research))
        self.assertEqual(opener.open.call_count, 1)
        request_body = json.loads(opener.open.call_args.args[0].data)
        self.assertEqual(request_body['thinking'], {'type': 'disabled'})
        model_input = json.loads(request_body['messages'][1]['content'])
        self.assertNotIn('points', model_input['series'][0])
        self.assertEqual(model_input['series'][0]['last'], self.request['series'][0]['points'][-1])

    def test_invalid_html_is_repaired_once(self):
        self.request = json.loads((ROOT / 'examples/research-request.json').read_text())
        research = (ROOT / 'examples/research.json').read_text()
        opener = Mock()
        opener.open.side_effect = [self.response('<div>fragment</div>'), self.response(research)]
        with patch('presentation_core.model_worker.load_arm', return_value=(
                {'url': 'https://example.invalid/chat/completions', 'model': 'dummy'}, 'test-secret')), \
                patch('presentation_core.model_worker.urllib.request.build_opener', return_value=opener):
            self.assertEqual(plan(self.request, self.config), json.loads(research))
        self.assertEqual(opener.open.call_count, 2)

    def test_invalid_research_content_is_repaired(self):
        request = json.loads((ROOT / 'examples/research-request.json').read_text())
        research = json.loads((ROOT / 'examples/research.json').read_text())
        without_headline = {key: value for key, value in research.items() if key != 'headline'}
        for invalid in (without_headline, dict(research, headline='库存上涨 4.5%'),
                        dict(research, title='额外的主题'),
                        dict(research, insights=research['insights'] * 2),
                        dict(research, insights=[{'heading': '其他', 'text': '解读'}]),
                        dict(research, insights=[dict(research['insights'][0], source_ids=['D1'])])):
            with self.subTest(invalid=invalid):
                opener = Mock()
                opener.open.side_effect = [self.response(json.dumps(invalid)), self.response(json.dumps(research))]
                with patch('presentation_core.model_worker.load_arm', return_value=(
                        {'url': 'https://example.invalid/chat/completions', 'model': 'dummy'}, 'test-secret')), \
                        patch('presentation_core.model_worker.urllib.request.build_opener', return_value=opener):
                    self.assertEqual(plan(request, self.config), research)
                self.assertEqual(opener.open.call_count, 2)

    def response(self, content):
        return io.BytesIO(json.dumps({'choices': [{'finish_reason': 'stop',
                            'message': {'content': content}}]}).encode())

    def test_structure_repair_uses_at_most_two_calls(self):
        opener = Mock()
        opener.open.side_effect = [self.response('not JSON'), self.response(json.dumps(self.deck))]
        with patch('presentation_core.model_worker.load_arm', return_value=(
                {'url': 'https://example.invalid/chat/completions', 'model': 'dummy'}, 'test-secret')), \
                patch('presentation_core.model_worker.urllib.request.build_opener', return_value=opener):
            result = plan(self.request, self.config)
        self.assertEqual(result['slides'], self.deck['slides'])
        self.assertEqual(opener.open.call_count, 2)

    def test_pptx_disables_thinking_and_shows_request_page_budget(self):
        self.request.update(max_slides=1, requested_slides=1)
        opener = Mock()
        opener.open.return_value = self.response(json.dumps(self.deck))
        with patch('presentation_core.model_worker.load_arm', return_value=(
                {'url': 'https://example.invalid/chat/completions', 'model': 'dummy'}, 'test-secret')), \
                patch('presentation_core.model_worker.urllib.request.build_opener', return_value=opener):
            plan(self.request, self.config)
        body = json.loads(opener.open.call_args.args[0].data)
        self.assertEqual(body['thinking'], {'type': 'disabled'})
        system = body['messages'][0]['content']
        self.assertIn('演示总页数必须恰好为 1 页', system)
        shown_schema = json.loads(system.split('输出 Schema：\n', 1)[1])
        self.assertEqual(shown_schema['properties']['slides']['minItems'], 1)
        self.assertEqual(shown_schema['properties']['slides']['maxItems'], 1)

    def test_layout_overflow_is_repaired_with_capacity_hint(self):
        self.request['max_slides'] = 5
        too_many = copy.deepcopy(self.deck)
        too_many['slides'] = too_many['slides'] * 6
        opener = Mock()
        opener.open.side_effect = [self.response(json.dumps(too_many)),
                                   self.response(json.dumps(self.deck))]
        with patch('presentation_core.model_worker.load_arm', return_value=(
                {'url': 'https://example.invalid/chat/completions', 'model': 'dummy'}, 'test-secret')), \
                patch('presentation_core.model_worker.urllib.request.build_opener', return_value=opener):
            result = plan(self.request, self.config)
        self.assertEqual(result['slides'], self.deck['slides'])
        self.assertEqual(opener.open.call_count, 2)
        repair = json.loads(opener.open.call_args.args[0].data)['messages'][-1]['content']
        self.assertIn('layout_overflow', repair)
        self.assertIn('内容页最多 5 页', repair)

    def test_repair_history_does_not_consume_material_budget(self):
        # Derive the material budget from the current prompt/schema, so new
        # supported layouts do not change what this retry regression measures.
        probe = Mock()
        probe.open.return_value = self.response(json.dumps(self.deck))
        with patch('presentation_core.model_worker.load_arm', return_value=(
                {'url': 'https://example.invalid/chat/completions', 'model': 'dummy'}, 'test-secret')), \
                patch('presentation_core.model_worker.urllib.request.build_opener', return_value=probe):
            plan(self.request, self.config)
        material = json.loads(probe.open.call_args.args[0].data)['messages']
        self.config['max_input_tokens'] = sum(len(m['content'].encode()) + 32 for m in material) + 100
        opener = Mock()
        opener.open.side_effect = [self.response('x' * 5000),
                                   self.response(json.dumps(self.deck))]
        with patch('presentation_core.model_worker.load_arm', return_value=(
                {'url': 'https://example.invalid/chat/completions', 'model': 'dummy'}, 'test-secret')), \
                patch('presentation_core.model_worker.urllib.request.build_opener', return_value=opener):
            result = plan(self.request, self.config)
        self.assertEqual(result['slides'], self.deck['slides'])
        self.assertEqual(opener.open.call_count, 2)

    def test_misplaced_speaker_notes_brace_is_repaired(self):
        malformed = json.dumps(self.deck, separators=(',', ':')).replace(
            '}],"speaker_notes"', '}]},"speaker_notes"')
        self.assertIn('}]},"speaker_notes"', malformed)
        opener = Mock()
        opener.open.return_value = self.response(malformed)
        with patch('presentation_core.model_worker.load_arm', return_value=(
                {'url': 'https://example.invalid/chat/completions', 'model': 'dummy'}, 'test-secret')), \
                patch('presentation_core.model_worker.urllib.request.build_opener', return_value=opener):
            result = plan(self.request, self.config)
        self.assertEqual(result['slides'], self.deck['slides'])
        self.assertEqual(opener.open.call_count, 1)

    def test_html_page_budget_is_not_consumed_by_pptx_source_pages(self):
        self.request['target_format'] = 'html'
        self.request['max_slides'] = 3
        base = self.request['sources'][0]
        self.request['sources'] = [{**base, 'id': f's{i}', 'title': f'来源{i}',
                                    'description': '说明' * 40} for i in range(30)]
        opener = Mock()
        opener.open.return_value = self.response('<html></html>')
        with patch('presentation_core.model_worker.load_arm', return_value=(
                {'url': 'https://example.invalid/chat/completions', 'model': 'dummy'}, 'test-secret')), \
                patch('presentation_core.model_worker.urllib.request.build_opener', return_value=opener):
            with self.assertRaises(PresentationError) as caught:
                plan(self.request, self.config)
        self.assertNotEqual(caught.exception.code, 'invalid_request')
        self.assertGreaterEqual(opener.open.call_count, 1)


    def test_credentials_require_private_file_and_no_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = root / 'model.key'
            key.write_text('not-a-real-api-key')
            key.chmod(0o600)
            deployment = root / 'deployment.json'
            arm = {'url': 'https://example.invalid/chat/completions', 'model': 'dummy', 'key': 'model.key'}
            deployment.write_text(json.dumps({'arms': {'deepseek-official': arm}}))
            config = {**self.config, 'deployment_config': str(deployment), 'credential_dir': tmp}
            self.assertEqual(load_arm(config)[0]['model'], 'dummy')
            key.chmod(0o644)
            with self.assertRaises(PresentationError):
                load_arm(config)
            key.chmod(0o600)
            arm['key'] = '../model.key'
            deployment.write_text(json.dumps({'arms': {'deepseek-official': arm}}))
            with self.assertRaises(PresentationError):
                load_arm(config)


if __name__ == '__main__':
    unittest.main()
