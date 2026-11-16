"""Repository-owned HTML template selection; no machine-specific paths."""
import json

from .contracts import ROOT, PresentationError

REGISTRY = ROOT / 'visuals/html-templates.json'


def registry():
    value = json.loads(REGISTRY.read_text(encoding='utf-8'))
    if value.get('default') not in value.get('templates', {}):
        raise PresentationError('invalid_request', 'HTML 默认模板未注册')
    return value


def resource(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise PresentationError('invalid_request', 'HTML 模板资源不在 skill 能力包中')
    return path.read_text(encoding='utf-8')


def selected(name=None):
    values = registry()
    name = name or values['default']
    if name not in values['templates']:
        raise PresentationError('invalid_html', 'HTML 模板未注册')
    return dict(values['templates'][name], name=name)


def styles(template):
    return '\n'.join(resource(path) for path in template['styles'])


def instructions(template):
    return resource(template['prompt']) if template.get('prompt') else ''
