"""One-shot model worker. Never emits credential contents or upstream errors."""
from __future__ import annotations

import json
import os
import re
import socket
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .contracts import ROOT, PresentationError, checked_deck, pages, schema, source_pages


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PresentationError('model_unavailable', '不允许模型端点重定向')


def load_arm(config):
    try:
        deployment = Path(config['deployment_config'])
        if not deployment.is_absolute():
            raise ValueError()
        arm = json.loads(deployment.read_text())['arms'][config['model_arm']]
        url = urllib.parse.urlsplit(arm['url'])
        if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password:
            raise ValueError()
        if url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError()
        if not isinstance(arm['model'], str) or not arm['model']:
            raise ValueError()
        name = arm['key']
        if not isinstance(name, str) or Path(name).name != name or name in ('.', '..'):
            raise ValueError()
        path = Path(config['credential_dir']) / name
        if any(p.is_symlink() for p in [path, *path.parents]):
            raise ValueError()
        st, parent = path.stat(), path.parent.stat()
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid()
                or stat.S_IMODE(st.st_mode) != 0o600 or parent.st_uid != os.getuid()
                or stat.S_IMODE(parent.st_mode) != 0o700):
            raise ValueError()
        secret = path.read_text().strip()
        if not secret or len(secret) > 4096 or any(c in secret for c in '\r\n\x00'):
            raise ValueError()
        return arm, secret
    except (OSError, ValueError, KeyError, TypeError):
        raise PresentationError('model_auth_failed', '部署配置或密钥文件无效') from None


def repair_deck_syntax(content):
    """Remove one extra '}' when the model puts speaker_notes outside the slide.

    Observed deterministic pattern: ... "blocks": [{...}]}, "speaker_notes": ...
    The brace repair only changes punctuation; structure checks still run.
    """
    return re.sub(r'\]\s*\}\s*,\s*("speaker_notes"\s*:)', r'],\1', content)


def plan(request, config):
    arm, secret = load_arm(config)
    html_mode = request['target_format'] == 'html'
    prompt_file = 'html.md' if html_mode else 'planner.md'
    prompt = (ROOT / 'prompts' / prompt_file).read_text().split('```text\n', 1)[1].split('```', 1)[0]
    if html_mode:
        from .html_templates import selected, instructions
        html_template = selected()
        prompt += '\n' + instructions(html_template)
    max_slides = request.get('max_slides', 8)
    if request.get('requested_slides') is not None:
        prompt += '\n本次演示总页数必须恰好为 ' + str(request['requested_slides']) + ' 页，包含封面和来源页。'
    content_limit = None
    if not html_mode:
        source_count = len(source_pages(request))
        content_limit = max_slides - 1 - source_count
        if content_limit < 1:
            raise PresentationError('invalid_request', '来源页数超过 max_slides 预算')
        content_limit = min(10, content_limit)
        deck_schema = schema('deck')
        # The schema shown to the model carries this request's real page budget.
        deck_schema['properties']['slides']['maxItems'] = content_limit
        if request.get('requested_slides') is not None:
            deck_schema['properties']['slides']['minItems'] = content_limit
        prompt += ('\n本次 max_slides=' + str(max_slides) +
                   '：内容页最多 ' + str(content_limit) + ' 页；封面和 ' + str(source_count) +
                   ' 页来源由程序追加。'
                   '\n输出 Schema：\n' + json.dumps(deck_schema, ensure_ascii=False, separators=(',', ':')))
    messages = [{'role': 'system', 'content': prompt},
                {'role': 'user', 'content': json.dumps(request, ensure_ascii=False)}]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for attempt in range(config['max_model_attempts']):
        # Conservative UTF-8 byte budget, NOT an exact vendor token count.
        # Only system+request materials are capped; repair turns are bounded
        # model output and must not disqualify an otherwise valid retry.
        material = messages[:2]
        if sum(len(m['content'].encode()) + 32 for m in material) > config['max_input_tokens']:
            raise PresentationError('invalid_request', '材料超过保守输入预算')
        body_value = {'model': arm['model'], 'messages': messages, 'stream': False,
                      'temperature': 0, 'max_tokens': config['max_output_tokens']}
        if config['model_arm'] == 'deepseek-official':
            # Match the existing official relay's disabled-thinking option:
            # reserve the output budget for the document rather than reasoning.
            body_value['thinking'] = {'type': 'disabled'}
        body = json.dumps(body_value).encode()
        req = urllib.request.Request(arm['url'], data=body, method='POST', headers={
            'Content-Type': 'application/json', 'Authorization': 'Bearer ' + secret})
        try:
            with opener.open(req, timeout=config['model_timeout_seconds']) as response:
                raw = response.read(262145)
            if len(raw) > 262144:
                raise PresentationError('invalid_html' if html_mode else 'invalid_deck', '模型响应过大')
            envelope = json.loads(raw)
            choice = envelope['choices'][0]
            if choice.get('finish_reason') != 'stop':
                raise PresentationError('invalid_html' if html_mode else 'invalid_deck', '模型输出未完整结束')
            content = choice['message']['content']
            if not isinstance(content, str):
                raise ValueError()
        except urllib.error.HTTPError as exc:
            raise PresentationError('model_auth_failed' if exc.code in (401, 403) else 'model_unavailable',
                                    '模型 HTTP 请求失败') from None
        except (TimeoutError, socket.timeout):
            raise PresentationError('model_timeout', '模型调用超时') from None
        except urllib.error.URLError as exc:
            code = 'model_timeout' if isinstance(exc.reason, (TimeoutError, socket.timeout)) else 'model_unavailable'
            raise PresentationError(code, '模型连接失败') from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise PresentationError('invalid_html' if html_mode else 'invalid_deck', '模型响应不是完整内容') from None
        try:
            if html_mode:
                from .render_html import Document, normalize
                html = normalize(content, request, template=html_template['name'])[0]
                doc = Document()
                doc.feed(html)
                if not doc.commodity:
                    raise PresentationError('invalid_html', '新演示必须包含 meta name="presentation-theme" content="commodity-v2"，使用给定语义组件，由程序注入统一主题')
                return html
            deck = json.loads(repair_deck_syntax(content))
            deck, _ = checked_deck(request, deck)
            pages(request, deck)
            return deck
        except (ValueError, PresentationError) as exc:
            code = exc.code if isinstance(exc, PresentationError) else 'invalid_deck'
            if attempt + 1 >= config['max_model_attempts']:
                message = exc.message if isinstance(exc, PresentationError) else '模型内容不是有效 JSON'
                raise PresentationError(code, message) from None
            hint = ''
            if code == 'layout_overflow' and not html_mode:
                hint = ('；内容页最多 ' + str(content_limit) + ' 页，表格含表头最多 5 行且每格文字更短，'
                        '要点页合计不超过 12 行')
            elif code == 'layout_overflow' and html_mode:
                hint = ('；整个 HTML 最多 ' + str(max_slides) +
                        ' 个 section.slide，包含封面和来源页，请合并或删减内容页')
            elif code == 'invalid_deck':
                hint = '；表格最多 5 列（headers 和每行最多 5 项），版式必须与块类型匹配'
            messages.extend([{'role': 'assistant', 'content': content},
                             {'role': 'user', 'content': '结构校验失败：' + code +
                              ('；' + exc.message if isinstance(exc, PresentationError) else '') +
                              hint +
                              '。请按原材料修复结构、保留完整来源，不增加事实。只返回' +
                              ('完整 HTML 文档。' if html_mode else ' JSON。')}])
    raise PresentationError('invalid_deck', '模型规划失败')


def main():
    try:
        raw = sys.stdin.read(524289)
        if len(raw.encode()) > 524288:
            raise PresentationError('invalid_request', '请求过大')
        payload = json.loads(raw)
        field = 'html' if payload['request']['target_format'] == 'html' else 'deck'
        result = {field: plan(payload['request'], payload['config'])}
    except PresentationError as exc:
        result = {'error': exc.code, 'message': exc.message}
    except Exception:
        result = {'error': 'model_unavailable'}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
