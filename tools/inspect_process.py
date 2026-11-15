"""Read-only inventory of modules and exported APIs in the chosen game process."""
import argparse
import json
from pathlib import Path

import frida


AGENT = r"""
rpc.exports.inventory = function () {
  return {arch: Process.arch, pointerSize: Process.pointerSize, pid: Process.id,
    modules: Process.enumerateModules().map(m => ({name: m.name, base: m.base.toString(),
      path: m.path, size: m.size,
      exports: m.enumerateExports().filter(e => /lua|il2cpp_(domain|thread|assembly|class|field|method|runtime|object|image)/i.test(e.name))
          .map(e => ({name:e.name, address:e.address.toString(), type:e.type}))}))};
};
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("address")
    parser.add_argument("pid", type=int)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    device = frida.get_device_manager().add_remote_device(args.address)
    session = device.attach(args.pid)
    try:
        script = session.create_script(AGENT)
        script.load()
        result = script.exports_sync.inventory()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({"arch": result["arch"], "pid": result["pid"],
                          "modules": len(result["modules"]),
                          "interesting": [{"name": m["name"], "exports": len(m["exports"])}
                                          for m in result["modules"] if m["exports"]]}, indent=2))
    finally:
        session.detach()


if __name__ == "__main__":
    main()
