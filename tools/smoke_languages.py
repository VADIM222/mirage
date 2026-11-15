"""Check both saved languages in the real Windows package, without game input."""
import argparse
import json
from pathlib import Path
import subprocess

from mirage.storage import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    executable = root / 'dist/Mirage/Mirage.exe'
    result = {}
    for language in ('ru', 'en'):
        data = args.output / language
        store = Store(data / 'mirage.sqlite3')
        store.set_preference('language', language)
        store.event(None, 'info', 'Ручная остановка; автоматическое возобновление приостановлено')
        image = args.output / f'{language}.png'
        completed = subprocess.run([str(executable), '--data-dir', str(data), '--smoke-image', str(image)],
            cwd=root, timeout=60, check=True)
        if not image.is_file() or image.stat().st_size < 1000:
            raise RuntimeError(f'{language}: package screenshot is missing')
        result[language] = {'exit_code': completed.returncode, 'image': str(image),
                            'saved_language': store.preference('language')}
    (args.output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
