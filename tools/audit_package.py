"""Compare embedded Mirage modules and its reader with the current source tree."""
import argparse
import hashlib
import json
from pathlib import Path
import types

from PyInstaller.archive.readers import CArchiveReader


def normalized(code):
    if not isinstance(code,types.CodeType):return code
    return code.replace(co_filename='',co_consts=tuple(normalized(value) for value in code.co_consts))


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];exe=root/'dist/Mirage/Mirage.exe'
    archive=CArchiveReader(str(exe));pyz=archive.open_embedded_archive('PYZ.pyz');modules={}
    for name in pyz.toc:
        if name!='mirage' and not name.startswith('mirage.'):continue
        source=root/'src'/Path(*name.split('.'))
        source=source/'__init__.py' if source.is_dir() else source.with_suffix('.py')
        if not source.is_file():raise RuntimeError(f'Embedded module without current source: {name}')
        code=compile(source.read_bytes(),str(source),'exec',dont_inherit=True,optimize=0)
        modules[name]=normalized(pyz.extract(name))==normalized(code)
    required={'mirage.scout_places','mirage.scout_fog','mirage.scout_caves','mirage.cave_rewards','mirage.vip_daily',
        'mirage.workflows','mirage.controller','mirage.ui','mirage.memory','mirage.barbarians','mirage.barbarian_chain',
        'mirage.barbarian_position','mirage.barbarian_navigation','mirage.commanders',
        'mirage.i18n','mirage.localized_widgets'}
    if not required<=set(modules):raise RuntimeError('Required current modules missing from package')
    reader=root/'src/mirage/agents/state_reader.js';packed=root/'dist/Mirage/_internal/mirage/agents/state_reader.js'
    result={'modules':modules,'reader_matches':digest(reader)==digest(packed),
        'reader_sha256':digest(reader),'exe_sha256':digest(exe)}
    result['locales']={str(path.relative_to(root/'src/mirage')):
        digest(path)==digest(root/'dist/Mirage/_internal/mirage'/path.relative_to(root/'src/mirage'))
        for path in (root/'src/mirage/locales').glob('*.json')}
    result['live_html_matches']=digest(root/'src/mirage/assets/live.html')==digest(root/'dist/Mirage/_internal/mirage/assets/live.html')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf8')
    if (not all(modules.values()) or not result['reader_matches'] or not result['locales']
            or not all(result['locales'].values()) or not result['live_html_matches']):
        raise RuntimeError('Package/source mismatch')
    print(json.dumps({'matched_modules':len(modules),**{key:value for key,value in result.items() if key!='modules'}}))


if __name__=='__main__':main()
