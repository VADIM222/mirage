"""Bounded real-device validation. Each requested game must yield its own state."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import threading
import time

from mirage.adb import Adb
from mirage.emulators import Discovery
from mirage.memory import Reader
from mirage.model import Power


def check(instance, seconds, directory):
    result = {"instance": instance.id, "cpus": instance.cpus, "memory_mb": instance.memory_mb,
              "readings": [], "error": None}
    reader = Reader(instance)
    try:
        reader.connect()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            before = time.monotonic()
            state = reader.snapshot()
            result["readings"].append({"player_id": state.player_id, "pid": state.pid,
                                       "clock": state.values["server_time"],
                                       "latency_ms": round((time.monotonic() - before) * 1000, 1),
                                       "fresh": state.fresh(time.monotonic())})
            threading.Event().wait(1)
    except Exception as error:
        result["error"] = str(error)
    finally:
        reader.close()
    try:
        adb = Adb(instance)
        adb.connect()
        image = directory / f"{instance.id.replace(':', '-')}.png"
        image.write_bytes(adb.screenshot())
        result["screenshot"] = str(image)
    except Exception as error:
        result["screenshot_error"] = str(error)
    readings = result["readings"]
    result["clock_advanced"] = len({r["clock"] for r in readings}) > 1
    result["passed"] = bool(not result["error"] and result["clock_advanced"] and all(r["fresh"] for r in readings))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("instances", nargs="+")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-ready", type=float, default=90)
    args = parser.parse_args()
    if not 1 <= len(args.instances) <= 3:
        parser.error("This workstation validation supports at most three games")
    deadline = time.monotonic() + args.wait_ready
    while True:
        instances = {i.id: i for i in Discovery().discover()}
        selected = [instances[key] for key in args.instances]
        if all(i.power == Power.ONLINE for i in selected):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Requested emulator instances did not become ready")
        threading.Event().wait(1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=len(selected)) as pool:
        futures = [pool.submit(check, instance, args.seconds, args.output.parent) for instance in selected]
        results = [future.result() for future in as_completed(futures)]
    document = {"mode": "real Android processes", "requested": len(selected),
                "passed": all(r["passed"] for r in results), "results": results}
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": document["passed"], "results": [
        {"instance": r["instance"], "snapshots": len(r["readings"]), "error": r["error"]} for r in results]}, ensure_ascii=True))
    raise SystemExit(0 if document["passed"] else 1)


if __name__ == "__main__":
    main()
