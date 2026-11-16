"""Observable contracts of the commodity presentation components."""
import copy
import json
import re
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from presentation_core import render
from presentation_core.contracts import ROOT, PresentationError, checked_deck, pages, validate_chart
from presentation_core.render_html import normalize
from presentation_core.render_pptx import chart_axis
from presentation_core.html_templates import selected


class VisualTests(unittest.TestCase):
    def setUp(self):
        self.request = json.loads((ROOT / 'examples/commodity-request.json').read_text())
        self.deck = json.loads((ROOT / 'examples/commodity-deck.json').read_text())
        self.html = (ROOT / 'examples/commodity.html').read_text()

    def test_html_is_single_file_idempotent_and_keeps_chart_values(self):
        result, count = normalize(self.html, self.request)
        self.assertEqual(count, 8)
        self.assertEqual(normalize(result, self.request)[0], result)
        self.assertEqual(result.count('<style id="commodity-theme">'), 1)
        self.assertEqual(result.count('<script id="commodity-runtime">'), 1)
        self.assertNotIn('<script src=', result)
        self.assertIn('14800, 14650, 14550, 14480', result)
        empty = re.sub(r'<script class="chart-data"[\s\S]*?</script>', '', self.html)
        with self.assertRaises(PresentationError):
            normalize(empty, self.request)
        self.assertIn('Content-Security-Policy', result)

    def test_incomplete_or_nonfinite_chart_is_rejected_in_both_formats(self):
        chart = self.deck['slides'][2]['blocks'][0]
        for values in ([1, 2], [1, 2, 3, float('nan')], [1, 2, 3, float('inf')]):
            bad = {**chart, 'series': [{'name': '库存', 'values': values}]}
            with self.subTest(values=values), self.assertRaises(PresentationError):
                validate_chart(bad)
            html = self.html.replace(json.dumps(chart, ensure_ascii=False), json.dumps(bad, ensure_ascii=False))
            with self.assertRaises(PresentationError):
                normalize(html, self.request)

    def test_own_runtime_used_instead_of_model_executable_script(self):
        result, _ = normalize(self.html.replace('</body>', '<script>alert(1)</script></body>'), self.request)
        self.assertNotIn('alert(1)', result)
        self.assertEqual(result.count('<script id="commodity-runtime">'), 1)
        self.assertIn('14800, 14650, 14550, 14480', result)

    def test_default_blueprint_embeds_actual_upstream_css(self):
        result, _ = normalize(self.html, self.request)
        upstream = (Path(__file__).resolve().parents[1] /
                    selected('knowledge-arch-blueprint')['upstream']).with_name('style.css')
        bundled = ROOT / 'visuals/templates/knowledge-arch-blueprint/style.css'
        self.assertEqual(bundled.read_bytes(), upstream.read_bytes())
        self.assertIn(bundled.read_text(), result)
        self.assertIn('class="tpl-knowledge-arch-blueprint"', result)
        self.assertIn('data-template="knowledge-arch-blueprint"', result)
        self.assertTrue((bundled.parent / 'LICENSE').is_file())

    def test_saved_commodity_template_keeps_its_style_across_normalization(self):
        legacy, _ = normalize(self.html, self.request, template='commodity-v2')
        self.assertNotIn('tpl-knowledge-arch-blueprint', legacy)
        self.assertIn('data-template="commodity-v2"', legacy)
        self.assertEqual(normalize(legacy, self.request)[0], legacy)
        blueprint, _ = normalize(legacy, self.request, template='knowledge-arch-blueprint')
        self.assertIn('class="tpl-knowledge-arch-blueprint"', blueprint)
        self.assertNotEqual(blueprint, legacy)

    def test_native_chart_is_editable_and_retains_workbook_and_data(self):
        from pptx import Presentation
        with tempfile.TemporaryDirectory() as tmp:
            result = render({**self.request, 'target_format': 'pptx'}, self.deck, config={'output_root': tmp})
            self.assertEqual(result['status'], 'succeeded', result.get('error'))
            file = Path(result['artifacts'][0]['local_path'])
            prs = Presentation(file)
            chart = next(s.chart for s in prs.slides[3].shapes if s.has_chart)
            self.assertEqual(list(chart.series[0].values), [14800, 14650, 14550, 14480])
            self.assertEqual([c.label for c in chart.plots[0].categories], ['周1', '周2', '周3', '周4'])
            self.assertEqual(chart.value_axis.minimum_scale, 14400)
            self.assertEqual(chart.value_axis.maximum_scale, 15000)
            self.assertIn('纵轴非零起点', '\n'.join(s.text for s in prs.slides[3].shapes if s.has_text_frame))
            self.assertEqual(prs.slides[3].notes_slide.notes_text_frame.text, self.deck['slides'][2]['speaker_notes'])
            with ZipFile(file) as archive:
                self.assertTrue(any(n.startswith('ppt/embeddings/') and n.endswith('.xlsx') for n in archive.namelist()))
            for slide in prs.slides:
                for shape in slide.shapes:
                    self.assertLessEqual(shape.left + shape.width, prs.slide_width + 1)
                    self.assertLessEqual(shape.top + shape.height, prs.slide_height + 1)

    def test_bar_supports_negative_values_and_zero_baseline(self):
        from pptx import Presentation
        block = self.deck['slides'][2]['blocks'][0]
        block.update(kind='bar', unit='万吨')
        block['series'][0]['values'] = [-150, -100, 0, 70]
        with tempfile.TemporaryDirectory() as tmp:
            result = render({**self.request, 'target_format': 'pptx'}, self.deck, config={'output_root': tmp})
            self.assertEqual(result['status'], 'succeeded', result.get('error'))
            prs = Presentation(result['artifacts'][0]['local_path'])
            chart = next(s.chart for s in prs.slides[3].shapes if s.has_chart)
            self.assertEqual(list(chart.series[0].values), [-150, -100, 0, 70])
            self.assertLessEqual(chart.value_axis.minimum_scale, -150)
            self.assertGreaterEqual(chart.value_axis.maximum_scale, 70)
        self.assertEqual(chart_axis([-10, -5], bar=True)[1], 0)

    def test_long_kpi_value_fails_before_rendering_instead_of_clipping(self):
        self.deck['slides'][1]['blocks'][0]['items'][0]['value'] = '1234567890123456'
        deck, _ = checked_deck(self.request, self.deck)
        with self.assertRaises(PresentationError) as caught:
            pages(self.request, deck)
        self.assertEqual(caught.exception.code, 'layout_overflow')

    def test_requested_page_count_is_enforced_for_both_files(self):
        request = {**self.request, 'max_slides': 4, 'requested_slides': 4}
        with self.assertRaises(PresentationError):
            normalize(self.html, request)
        with self.assertRaises(PresentationError):
            checked_deck(request, self.deck)
        deck = {**self.deck, 'slides': self.deck['slides'][1:3]}
        accepted, _ = checked_deck(request, deck)
        self.assertEqual(len(pages(request, accepted)), 4)
        sections = re.findall(r'<section class="slide[\s\S]*?</section>', self.html)
        small = re.sub(r'<main class="deck">[\s\S]*?</main>',
                       lambda _: '<main class="deck">' + ''.join(sections[i] for i in (0, 2, 3, 7)) + '</main>', self.html)
        self.assertEqual(normalize(small, request)[1], 4)


if __name__ == '__main__':
    unittest.main()
