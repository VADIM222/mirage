"""Inspect explicitly named raw Lua paths using the production read-only agent."""
import argparse
import json
from pathlib import Path

from mirage.emulators import Discovery
from mirage.memory import Reader


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('instance')
    parser.add_argument('paths',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--server',required=True)
    parser.add_argument('--depth',type=int,default=0)
    args=parser.parse_args()
    instance=next(i for i in Discovery().discover() if i.id==args.instance)
    reader=Reader(instance,args.server)
    try:
        reader.connect()
        result=reader.script.exports_sync.snapshot(json.loads(args.paths.read_text(encoding='utf-8')),args.depth)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print({key:len(value) if isinstance(value,dict) else type(value).__name__ for key,value in result['values'].items()})
    finally:
        reader.close()


if __name__=='__main__':
    main()
