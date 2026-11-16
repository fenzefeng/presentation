"""Execute a copied skill from outside the repository, without a Fusion checkout."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zipfile import ZipFile


class PortableSkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'copied-skill'
        shutil.copytree(Path(__file__).resolve().parents[1], self.bundle,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.cwd = self.root / 'empty-project'
        self.cwd.mkdir()
        self.env = dict(os.environ)
        self.env.pop('PYTHONPATH', None)
        self.examples = self.bundle / 'scripts/presentation_core/examples'

    def cli(self, *args):
        proc = subprocess.run([sys.executable, '-B', str(self.bundle / 'scripts/run.py'), *args],
                              cwd=self.cwd, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def test_copied_skill_renders_both_formats_and_has_no_fusion_imports(self):
        for fmt, flag, example, request in [
                ('html', '--html', 'presentation.html', 'request.json'),
                ('pptx', '--deck', 'deck.json', 'request.json'),
                ('html', '--html', 'commodity.html', 'commodity-request.json'),
                ('pptx', '--deck', 'commodity-deck.json', 'commodity-request.json')]:
            result = self.cli('render', '--input', str(self.examples / request),
                              flag, str(self.examples / example), '--output-root', str(self.root / fmt))
            artifact = Path(result['artifacts'][0]['local_path'])
            self.assertEqual(artifact.suffix, '.' + fmt)
            if example == 'commodity.html':
                self.assertIn('<script id="commodity-runtime">', artifact.read_text())
            if fmt == 'pptx':
                with ZipFile(artifact) as archive:
                    self.assertIsNone(archive.testzip())
        code = ("import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
                "from presentation_core.runtime import SKILL_DIR; "
                "assert SKILL_DIR==Path(sys.argv[2]); "
                "assert not any(n=='fusion' or n.startswith('fusion.') for n in sys.modules)")
        subprocess.run([sys.executable, '-B', '-c', code, str(self.bundle / 'scripts'), str(self.bundle)],
                       cwd=self.cwd, env=self.env, check=True, capture_output=True, timeout=30)

    def test_model_subprocess_runs_inside_copied_skill(self):
        html = (self.examples / 'blueprint.html').read_text()
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                body = json.dumps({'choices': [{'message': {'content': html}, 'finish_reason': 'stop'}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        credentials = self.root / 'credentials'
        credentials.mkdir(mode=0o700)
        key = credentials / 'test.key'
        key.write_text('synthetic-test-key')
        key.chmod(0o600)
        deployment = self.root / 'deployment.json'
        deployment.write_text(json.dumps({'arms': {'test': {
            'url': f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
            'model': 'test-model', 'key': 'test.key'}}}))
        config = self.root / 'config.json'
        config.write_text(json.dumps({'deployment_config': str(deployment), 'model_arm': 'test',
                                     'credential_dir': str(credentials), 'output_root': str(self.root / 'generated')}))
        result = self.cli('generate', '--input', str(self.examples / 'request.json'), '--config', str(config))
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['provenance']['template_version'], 'knowledge-arch-blueprint-v1')
        self.assertEqual(requests[0]['model'], 'test-model')


if __name__ == '__main__':
    unittest.main()
