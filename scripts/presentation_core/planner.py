"""Planner interface backed by an isolated credential-holding process."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .contracts import PresentationError


class ModelPlanner:
    def __init__(self, config):
        self.config = config

    def plan(self, request, *, deadline, cancel=None):
        payload = json.dumps({'request': request, 'config': self.config}, ensure_ascii=False)
        # No secrets are supplied through arguments or parent process reads.
        env = {k: v for k, v in os.environ.items()
               if not any(word in k.upper() for word in ('API_KEY', 'TOKEN', 'SECRET', 'SIGNCODE', 'PYTHONPATH'))}
        proc = subprocess.Popen([sys.executable, '-B', '-m', __package__ + '.model_worker'],
                                cwd=Path(__file__).resolve().parent.parent, env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, start_new_session=True)
        try:
            first = True
            while True:
                if cancel is not None and cancel.is_set():
                    raise PresentationError('cancelled', '任务已取消')
                if time.monotonic() >= deadline:
                    raise PresentationError('deadline_exceeded', '模型规划超过总截止时间')
                try:
                    out, _ = proc.communicate(input=payload if first else None, timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    first = False
            if proc.returncode or len(out.encode()) > 300000:
                raise PresentationError('model_unavailable', '模型子进程未正常完成')
            try:
                result = json.loads(out)
            except ValueError:
                raise PresentationError('model_unavailable', '模型子进程输出无效') from None
            if 'error' in result:
                allowed = {'model_auth_failed', 'model_timeout', 'model_unavailable',
                           'invalid_deck', 'invalid_html', 'invalid_request', 'layout_overflow'}
                code = result['error'] if result['error'] in allowed else 'model_unavailable'
                raise PresentationError(code, result.get('message', '模型规划失败；请检查配置、连接或材料')[:300])
            return result['html' if request['target_format'] == 'html' else 'deck']
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
