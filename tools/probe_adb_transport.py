"""Read one ADB handshake without using or changing the global ADB server."""

import argparse
import json
import socket
import struct


def exact(connection: socket.socket, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        data = connection.recv(size - len(result))
        if not data:
            raise EOFError(f"Peer closed after {len(result)}/{size} bytes")
        result.extend(data)
    return bytes(result)


def probe(port: int) -> dict:
    command = int.from_bytes(b"CNXN", "little")
    body = b"host::features=shell_v2,cmd\0"
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.settimeout(5)
        connection.sendall(struct.pack("<6I", command, 0x01000000, 4096,
                                       len(body), sum(body), command ^ 0xFFFFFFFF) + body)
        header = exact(connection, 24)
        cmd, arg0, arg1, length, checksum, magic = struct.unpack("<6I", header)
        if length > 1024 * 1024:
            raise ValueError("Unreasonable ADB packet size")
        payload = exact(connection, length)
        return {"command": cmd.to_bytes(4, "little").decode("ascii", "replace"),
                "arg0": arg0, "arg1": arg1, "size": length,
                "checksum_valid": sum(payload) == checksum,
                "payload": payload.decode("utf-8", "replace") if cmd != int.from_bytes(b"AUTH", "little") else "<auth challenge>"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int)
    try:
        print(json.dumps(probe(parser.parse_args().port), ensure_ascii=False, indent=2))
    except (OSError, EOFError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
