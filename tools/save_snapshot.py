import argparse
import json
from pathlib import Path

from mirage.emulators import Discovery
from mirage.memory import Reader


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('instance')
    parser.add_argument('--server',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    instance=next(i for i in Discovery().discover() if i.id==args.instance)
    reader=Reader(instance,args.server)
    try:
        reader.connect()
        snapshot=reader.snapshot()
        args.output.write_text(json.dumps(snapshot.values,ensure_ascii=False,indent=2),encoding='utf-8')
        print({key:len(value) if isinstance(value,dict) else type(value).__name__ for key,value in snapshot.values.items()})
    finally:
        reader.close()


if __name__=='__main__':
    main()
