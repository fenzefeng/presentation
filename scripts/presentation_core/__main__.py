"""CLI for the self-contained presentation skill implementation."""
import argparse
import json
import signal
import sys
import threading
from pathlib import Path

from .contracts import PresentationError
from .service import generate, render


def read_json(path):
    if Path(path).stat().st_size > 524288:
        raise PresentationError('invalid_request', 'JSON 文件超过大小限制')
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description='将已有分析转换为 HTML 或 PPTX')
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('generate', 'render'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--input', required=True, help='分析及来源 JSON')
        cmd.add_argument('--config', help='私有运行配置 JSON')
        cmd.add_argument('--output-root', help='私有输出目录的绝对路径')
        cmd.add_argument('--format', choices=('html', 'pptx'), help='覆盖输入中的 target_format')
        if name == 'render':
            group = cmd.add_mutually_exclusive_group(required=True)
            group.add_argument('--deck', help='PPTX 离线演示结构 JSON')
            group.add_argument('--research', help='HTML 离线研究结构 JSON')
            group.add_argument('--html', help='已生成的完整 HTML 文件')
    args = parser.parse_args()
    cancel = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    signal.signal(signal.SIGTERM, lambda *_: cancel.set())
    try:
        request = read_json(args.input)
        config = read_json(args.config) if args.config else {}
        if not isinstance(request, dict) or not isinstance(config, dict):
            raise PresentationError('invalid_request', '输入和配置必须为 JSON 对象')
        if args.output_root:
            config['output_root'] = args.output_root
        if args.format:
            request['target_format'] = args.format
        if args.action == 'render':
            fmt = 'html' if args.html or args.research else 'pptx'
            if args.format and args.format != fmt:
                raise PresentationError('invalid_request', '--html / --research 对应 html，--deck 对应 pptx')
            request['target_format'] = fmt
            if args.html:
                if Path(args.html).stat().st_size > 262144:
                    raise PresentationError('invalid_html', 'HTML 文件超过大小限制')
                content = Path(args.html).read_text(encoding='utf-8')
            else:
                content = read_json(args.research or args.deck)
            result = render(request, content, config=config, cancel=cancel)
        else:
            result = generate(request, config=config, cancel=cancel)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] == 'succeeded' else 1
    except (OSError, ValueError, PresentationError) as exc:
        error = {'code': exc.code, 'message': exc.message} if isinstance(exc, PresentationError) else {
            'code': 'invalid_request', 'message': '无法读取 JSON 输入或配置'}
        print(json.dumps({'status': 'rejected', 'error': error}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
