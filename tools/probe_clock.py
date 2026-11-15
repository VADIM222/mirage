"""Find changing numeric clock fields without calling any game functions."""
import argparse
import json
import threading
from pathlib import Path

from mirage.emulators import Discovery
from mirage.memory import Reader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("instance")
    parser.add_argument("--server", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    instance = next(i for i in Discovery().discover() if i.id == args.instance)
    reader = Reader(instance, args.server)
    records = []
    try:
        reader.connect()
        for _ in range(3):
            raw = reader.script.exports_sync.snapshot({"timer": ["GameTimer"]}, 0)
            records.append({key: value for key,value in raw["values"]["timer"].items()
                            if type(value) in (int, float)})
            threading.Event().wait(0.5)
    finally:
        reader.close()
    changed = {key: [record.get(key) for record in records] for key in records[0]
               if len({record.get(key) for record in records}) > 1}
    args.output.write_text(json.dumps({"changed": changed, "records": records}, indent=2), encoding="utf-8")
    print(json.dumps(changed))


if __name__ == "__main__":
    main()
