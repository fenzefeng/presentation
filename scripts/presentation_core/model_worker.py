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

from .contracts import ROOT, PresentationError, checked_deck, checked_research, pages, schema


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
    prompt_file = 'research.md' if html_mode else 'planner.md'
    prompt = (ROOT / 'prompts' / prompt_file).read_text().split('```text\n', 1)[1].split('```', 1)[0]
    if html_mode:
        prompt += '\n输出 Schema：\n' + json.dumps(schema('research'), ensure_ascii=False, separators=(',', ':'))
    else:
        requested = request.get('requested_slides')
        content_limit = requested if requested is not None else request.get('max_slides', 8)
        deck_schema = schema('deck')
        # The schema shown to the model carries this request's real page budget.
        deck_schema['properties']['slides']['maxItems'] = content_limit
        deck_schema['properties']['slides']['items']['properties'].pop('caption')
        if requested is not None:
            deck_schema['properties']['slides']['minItems'] = requested
            prompt += f'\n本次演示总页数必须恰好为 {requested} 页。'
        else:
            prompt += f'\n本次演示最多 {content_limit} 页。'
        prompt += '\n输出 Schema：\n' + json.dumps(deck_schema, ensure_ascii=False, separators=(',', ':'))
    material = dict(request)
    if html_mode:
        material.pop('max_slides', None)
        material.pop('requested_slides', None)
    if material.get('series'):
        # The renderer reads every original observation from the request. The
        # model only needs the recorded range and a few values for context.
        material['series'] = [
            {**{k: v for k, v in item.items() if k != 'points'},
             'observations': len(item['points']), 'first': item['points'][0],
             'last': item['points'][-1],
             **({'points': item['points']} if not html_mode and len(item['points']) <= 12 else {})}
            for item in material['series']
        ]
    messages = [{'role': 'system', 'content': prompt},
                {'role': 'user', 'content': json.dumps(material, ensure_ascii=False)}]
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
                return checked_research(request, json.loads(content))
            deck = json.loads(repair_deck_syntax(content))
            deck, _ = checked_deck(request, deck)
            pages(request, deck)
            return deck
        except (ValueError, PresentationError) as exc:
            code = exc.code if isinstance(exc, PresentationError) else ('invalid_html' if html_mode else 'invalid_deck')
            if attempt + 1 >= config['max_model_attempts']:
                message = exc.message if isinstance(exc, PresentationError) else '模型内容不是有效 JSON'
                raise PresentationError(code, message) from None
            if code == 'invalid_deck' and not html_mode:
                # Replan from the original material with a smaller schema. Feeding
                # the malformed deck back can reproduce its invalid structure.
                slide_fields = deck_schema['properties']['slides']['items']['properties']
                slide_fields['layout']['enum'] = ['bullets']
                blocks = slide_fields['blocks']
                blocks['maxItems'] = 1
                blocks['items']['oneOf'] = [variant for variant in blocks['items']['oneOf']
                                             if variant['properties']['type']['const'] == 'bullets']
                retry_prompt = prompt.split('\n输出 Schema：\n', 1)[0]
                detail = exc.message if isinstance(exc, PresentationError) else '模型内容不是有效 JSON'
                retry_prompt += (
                    f'\n上次结构校验失败：{detail}。重新根据原材料规划，保留要求的页数。'
                    '本次每页只允许 layout=bullets 和一个 type=bullets 的块。'
                    '只返回一个符合新 Schema 的 JSON 对象。'
                    '\n输出 Schema：\n' + json.dumps(deck_schema, ensure_ascii=False, separators=(',', ':')))
                messages[0] = {'role': 'system', 'content': retry_prompt}
                continue
            hint = ''
            if code == 'layout_overflow' and not html_mode:
                hint = ('；内容页最多 ' + str(content_limit) + ' 页，表格含表头最多 5 行且每格文字更短，'
                        '要点页合计不超过 12 行')
            messages.extend([{'role': 'assistant', 'content': content},
                             {'role': 'user', 'content': '结构校验失败：' + code +
                              ('；' + exc.message if isinstance(exc, PresentationError) else '') +
                              hint +
                              '。请按原材料修复结构，保留已有数据口径，只返回 JSON。'}])
    raise PresentationError('invalid_deck', '模型规划失败')


def main():
    try:
        raw = sys.stdin.read(524289)
        if len(raw.encode()) > 524288:
            raise PresentationError('invalid_request', '请求过大')
        payload = json.loads(raw)
        field = 'research' if payload['request']['target_format'] == 'html' else 'deck'
        result = {field: plan(payload['request'], payload['config'])}
    except PresentationError as exc:
        result = {'error': exc.code, 'message': exc.message}
    except Exception:
        result = {'error': 'model_unavailable'}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
