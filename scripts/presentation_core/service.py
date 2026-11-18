"""Generation orchestration and atomic private artifact publication."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .contracts import PresentationError, checked_deck, normalize_request, pages, validate

DEFAULTS = {
    'model_arm': 'deepseek-official', 'credential_dir': str(Path.home() / '.config/e1-metric'),
    'output_root': str(Path.home() / '.local/share/fusion/presentations'),
    'template_version': 'commodity-v2', 'planner_version': 'planner-v2',
    'model_timeout_seconds': 60, 'total_timeout_seconds': 180, 'max_model_attempts': 2,
    'max_output_tokens': 8192, 'max_input_tokens': 24000, 'retention_days': 7,
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def write_json(path, value):
    with path.open('x', encoding='utf-8') as f:
        os.chmod(path, 0o600)
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def configuration(value=None):
    config = {**DEFAULTS, **(value or {})}
    # Existing deployments need no private configuration migration.
    if config['template_version'] == 'business-v1':
        config['template_version'] = 'commodity-v2'
    if config['planner_version'] == 'planner-v1':
        config['planner_version'] = 'planner-v2'
    if config['template_version'] != 'commodity-v2' or config['planner_version'] != 'planner-v2':
        raise PresentationError('invalid_request', '不支持的模板或规划器版本')
    for key in ('output_root', 'credential_dir'):
        if not isinstance(config[key], str) or '${' in config[key] or not Path(config[key]).is_absolute():
            raise PresentationError('invalid_request', f'{key} 必须是已展开的绝对路径')
    for key, maximum in (('model_timeout_seconds', 120), ('total_timeout_seconds', 600),
                         ('max_model_attempts', 2), ('max_output_tokens', 16384),
                         ('max_input_tokens', 32000), ('retention_days', 365)):
        if type(config[key]) is not int or not 1 <= config[key] <= maximum:
            raise PresentationError('invalid_request', f'{key} 超出允许范围')
    return config


def private_root(path):
    root = Path(path)
    for part in [*reversed(root.parents), root]:
        if part.is_symlink():
            raise PresentationError('storage_failed', '产物目录不能包含符号链接')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    st = root.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise PresentationError('storage_failed', '产物目录必须属于当前用户且权限为 700')
    return root


def run(request, *, content=None, config=None, planner=None, cancel=None):
    request = normalize_request(request)
    cfg = configuration(config)
    root = private_root(cfg['output_root'])
    generation_id = str(uuid.uuid4())
    final, temp = root / generation_id, root / ('.' + generation_id + '.tmp')
    temp.mkdir(mode=0o700)
    deadline = time.monotonic() + cfg['total_timeout_seconds']
    mode = 'offline' if content is not None else 'model'
    html_mode = request['target_format'] == 'html'
    result = {
        'schema_version': '1.0', 'generation_id': generation_id, 'status': 'failed',
        'created_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'input_sha256': hashlib.sha256(canonical(request)).hexdigest(),
        'slide_count': 0, 'artifacts': [], 'warnings': [], 'error': None,
        'provenance': {'mode': mode, 'model_arm': cfg['model_arm'] if mode == 'model' else None,
                       'template_version': 'direct-html-v1' if html_mode else cfg['template_version'],
                       'planner_version': ('research-v1' if html_mode else cfg['planner_version']) if mode == 'model' else None},
    }

    def checkpoint(stage):
        if cancel is not None and cancel.is_set():
            raise PresentationError('cancelled', '任务已取消')
        if time.monotonic() >= deadline:
            raise PresentationError('deadline_exceeded', '生成超过总截止时间')
        state = temp / 'status.json'
        # Atomic replacement for readers; no partial JSON exposed.
        next_state = temp / '.status.json'
        write_json(next_state, {'status': stage, 'generation_id': generation_id})
        next_state.replace(state)

    try:
        write_json(temp / 'request.json', request)
        checkpoint('planning' if mode == 'model' else 'validating')
        if content is None:
            if planner is None:
                from .planner import ModelPlanner
                planner = ModelPlanner(cfg)
            content = planner.plan(request, deadline=deadline, cancel=cancel)
        checkpoint('validating')
        fmt = request['target_format']
        if html_mode and isinstance(content, dict) and ('slides' not in content or mode == 'model'):
            from . import render_research as renderer
            view = renderer.document(request, content)
            slide_count = 0
            result['provenance']['template_version'] = 'research-v1'
            result['warnings'] = ['review_required'] + ([] if request['sources'] else ['sources_missing'])
            mime = 'text/html'
            write_json(temp / 'research.json', content)
        elif html_mode:
            from . import render_html as renderer
            content, slide_count = renderer.normalize(content, request)
            if '<style id="commodity-theme">' in content:
                from .html_templates import selected
                doc = renderer.Document()
                doc.feed(content)
                result['provenance']['template_version'] = selected(doc.template_id)['version']
            view = content
            result['warnings'] = ['review_required'] + ([] if request['sources'] else ['sources_missing'])
            mime = 'text/html'
        else:
            from . import render_pptx as renderer
            deck, warnings = checked_deck(request, content)
            view = pages(request, deck)
            slide_count = len(view)
            result['warnings'] = warnings
            write_json(temp / 'deck.json', deck)
            mime = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
        checkpoint('rendering')
        filename = 'presentation.' + fmt
        output = temp / filename
        # Create privately before the renderer opens it.
        output.touch(mode=0o600)
        renderer.render(view, output)
        checkpoint('verifying')
        renderer.verify(output, slide_count)
        checkpoint('verifying')
        result.update(status='succeeded', slide_count=slide_count, artifacts=[{
            'artifact_id': str(uuid.uuid4()), 'format': fmt, 'filename': filename,
            'media_type': mime, 'local_path': str(final / filename),
            'size_bytes': output.stat().st_size, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        }])
    except Exception as exc:
        if isinstance(exc, PresentationError):
            error = exc
        elif isinstance(exc, ImportError):
            error = PresentationError('render_dependency_missing', '缺少生成依赖，请安装 requirements.txt')
        elif isinstance(exc, OSError):
            error = PresentationError('storage_failed', '无法读写产物目录')
        else:
            error = PresentationError('render_failed', '生成或文件校验失败')
        result.update(status='cancelled' if error.code == 'cancelled' else 'failed',
                      slide_count=0, artifacts=[], error={'code': error.code, 'message': error.message})
        for file in temp.glob('presentation.*'):
            file.unlink(missing_ok=True)
    try:
        validate('result', result)
        write_json(temp / 'result.json', result)
        (temp / 'status.json').unlink(missing_ok=True)
        write_json(temp / 'status.json', {'status': result['status'], 'generation_id': generation_id})
        temp.rename(final)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return result


def generate(request, *, config=None, planner=None, cancel=None):
    return run(request, config=config, planner=planner, cancel=cancel)


def render(request, content, *, config=None, cancel=None):
    return run(request, content=content, config=config, cancel=cancel)
