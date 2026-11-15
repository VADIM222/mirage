"""List application-owned Russian text for the offline localization audit."""
import ast
from pathlib import Path
import re


CYRILLIC = re.compile(r'[\u0400-\u04ff]')


def source_strings(root=None):
    root = root or Path(__file__).resolve().parents[1] / 'src/mirage'
    result = {}
    for path in sorted(root.glob('*.py')):
        if path.name.startswith('i18n_'):
            continue
        tree = ast.parse(path.read_text(encoding='utf8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and CYRILLIC.search(node.value):
                result.setdefault(node.value, f'{path.name}:{node.lineno}')
    return result


if __name__ == '__main__':
    import json
    for text, location in source_strings().items():
        print(json.dumps([location, text], ensure_ascii=False))
