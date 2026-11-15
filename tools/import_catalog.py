"""Compile a numbered offline translation batch into the reviewable JSON catalog."""
import argparse
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('sources', type=Path)
    parser.add_argument('translations', type=Path)
    parser.add_argument('--output', type=Path, default=Path('src/mirage/locales/en.json'))
    args = parser.parse_args()
    sources = [json.loads(line)[1] for line in args.sources.read_text(encoding='utf8').splitlines()]
    numbered = {}
    for line in args.translations.read_text(encoding='utf8').splitlines():
        key, text = line.split('|', 1)
        index = int(key)
        if index in numbered:
            raise ValueError(f'Duplicate translation {index}')
        numbered[index] = text.replace(r'\n', '\n')
    if set(numbered) != set(range(1, len(sources) + 1)):
        raise ValueError('Incomplete translation batch')
    catalog = {}
    for index, source in enumerate(sources, 1):
        text = numbered[index]
        if not text.strip() or re.search(r'[\u0400-\u04ff]', text):
            raise ValueError(f'Invalid English translation {index}')
        catalog[source] = text
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(f'{len(catalog)} offline translations written to {args.output}')


if __name__ == '__main__':
    main()
