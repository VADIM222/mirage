from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="Mirage — независимый memory-first бот для RoK")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--diagnose", action="store_true", help="Показать реальные найденные экземпляры и завершиться")
    parser.add_argument("--smoke-image", type=Path, help="Проверить запуск настоящих виджетов и сохранить изображение")
    args = parser.parse_args()
    if args.diagnose:
        from .emulators import Discovery
        discovery = Discovery()
        print(json.dumps({"instances": [asdict(instance) for instance in discovery.discover()],
                          "errors": discovery.errors}, ensure_ascii=True, indent=2))
        return
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .controller import Controller
    from .storage import Store
    from .ui import Window
    data_dir = args.data_dir or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Mirage"
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Mirage")
    app.setOrganizationName("Mirage")
    store = Store(data_dir / "mirage.sqlite3")
    controller = Controller(store, auto_refresh=not bool(args.smoke_image))
    window = Window(store, controller)
    window.show()
    if args.smoke_image:
        from .emulators import Discovery
        controller.instances = Discovery().discover()
        window.refresh()

        def capture():
            args.smoke_image.parent.mkdir(parents=True, exist_ok=True)
            if not window.grab().save(str(args.smoke_image)):
                raise RuntimeError("Не удалось сохранить изображение окна")
            window.close()
        QTimer.singleShot(0, capture)
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
