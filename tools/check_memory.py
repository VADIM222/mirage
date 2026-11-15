"""Bounded live check of Mirage's production read-only adapter."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import threading
import time

from mirage.emulators import Discovery
from mirage.memory import Reader
from mirage.workflows import VERIFIED_WORKFLOWS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("instance")
    parser.add_argument("--server", default="/data/local/tmp/mirage-frida-server")
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", choices=tuple(VERIFIED_WORKFLOWS), help="Также проверить дополнительные поля сценария")
    args = parser.parse_args()
    instance = next(i for i in Discovery().discover() if i.id == args.instance)
    reader = Reader(instance, args.server)
    readings = []
    started = time.monotonic()
    try:
        reader.connect()
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            before = time.monotonic()
            extra = VERIFIED_WORKFLOWS[args.task].extra_paths if args.task else None
            reading = reader.snapshot(extra) if extra else reader.snapshot()
            readings.append({"pid": reading.pid, "player_id": reading.player_id,
                             "server_time": reading.values.get("server_time"),
                             "elapsed_ms": round((time.monotonic()-before)*1000, 2),
                             "resources": reading.values.get("resources"),
                             "building_count": len(reading.values.get("buildings") or {}),
                             "fresh": reading.fresh(time.monotonic())})
            threading.Event().wait(0.25)
        result = {"instance": instance.id, "game_version": reader.version,
                  "task": args.task,
                  "duration_seconds": round(time.monotonic()-started, 2), "readings": readings,
                  "clock_advanced": len({r["server_time"] for r in readings}) > 1}
    finally:
        reader.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key,value in result.items() if key!="readings"}))
    print(f"Snapshots: {len(readings)}")


if __name__ == "__main__":
    main()
