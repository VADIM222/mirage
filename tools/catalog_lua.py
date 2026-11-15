import argparse
import json
from pathlib import Path

from mirage.emulators import Discovery
from mirage.memory import Reader


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('instance')
    parser.add_argument('pattern')
    parser.add_argument('output',type=Path)
    parser.add_argument('--server',required=True)
    args=parser.parse_args()
    instance=next(i for i in Discovery().discover() if i.id==args.instance)
    reader=Reader(instance,args.server)
    try:
        reader.connect()
        result=reader.script.exports_sync.catalog(args.pattern)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('\n'.join(sorted(result)))
    finally:
        reader.close()


if __name__=='__main__':
    main()
