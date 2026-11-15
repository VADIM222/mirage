import argparse
from pathlib import Path

from mirage.emulators import Discovery
from mirage.runtime import install


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('instance')
    parser.add_argument('file',type=Path)
    args=parser.parse_args()
    instance=next(i for i in Discovery().discover() if i.id==args.instance)
    print(install(instance,args.file))


if __name__=='__main__':
    main()
