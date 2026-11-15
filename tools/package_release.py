"""Archive the complete Windows folder, including current bilingual documentation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    package = root / 'dist/Mirage'
    if not (package/'Mirage.exe').is_file() or not (package/'_internal/mirage/locales/en.json').is_file():
        raise RuntimeError('Build the bilingual Windows package first')
    for source in [root/'README.md', root/'README.en.md', *(root/'docs').glob('*.md')]:
        destination = package / source.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    files = sorted(path for path in package.rglob('*') if path.is_file())
    if any(path.suffix in ('.sqlite3', '.db', '.log') or 'data' in path.relative_to(package).parts for path in files):
        raise RuntimeError('Runtime data found inside the application package')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, 'w', compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, path.relative_to(package.parent))
    with args.output.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest().upper()
    checksum = args.output.with_suffix('.sha256')
    checksum.write_text(f'{digest}  {args.output.name}\n', encoding='ascii')
    print(json.dumps({'archive': str(args.output), 'sha256': digest, 'files': len(files),
                      'bytes': args.output.stat().st_size, 'checksum': str(checksum)}))


if __name__ == '__main__':
    main()
