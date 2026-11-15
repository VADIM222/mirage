"""Download a pinned official Frida server, validate both archive and ELF hashes."""
import argparse
import hashlib
import lzma
from pathlib import Path

import httpx

from mirage.runtime import FRIDA_ARCHIVE_SHA256, FRIDA_SERVER_SHA256, FRIDA_SERVER_URL


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    response=httpx.get(FRIDA_SERVER_URL,follow_redirects=True,timeout=httpx.Timeout(60,connect=10))
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest()!=FRIDA_ARCHIVE_SHA256:
        raise RuntimeError('Official archive digest mismatch')
    data=lzma.decompress(response.content)
    if hashlib.sha256(data).hexdigest()!=FRIDA_SERVER_SHA256:
        raise RuntimeError('Frida server digest mismatch')
    args.destination.parent.mkdir(parents=True,exist_ok=True)
    args.destination.write_bytes(data)
    print(args.destination)


if __name__=='__main__':
    main()
