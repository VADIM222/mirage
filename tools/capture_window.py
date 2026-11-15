"""Capture only the selected Windows application window for local diagnostics."""

import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path

from PySide6.QtWidgets import QApplication


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pid", type=int)
    parser.add_argument("output", type=Path)
    parser.add_argument("--desktop", action="store_true")
    args = parser.parse_args()
    handles = []
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == args.pid and user32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            area = (rect.right - rect.left) * (rect.bottom - rect.top)
            handles.append((area, hwnd))
        return True

    user32.EnumWindows(visit, 0)
    if not handles:
        raise SystemExit("No visible window for this process")
    app = QApplication([])
    hwnd = max(handles)[1]
    if args.desktop:
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        image = app.primaryScreen().grabWindow(0,rect.left,rect.top,
                                               rect.right-rect.left,rect.bottom-rect.top)
    else:
        image = app.primaryScreen().grabWindow(hwnd)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if image.isNull() or not image.save(str(args.output)):
        raise SystemExit("Window capture failed")
    print(args.output)


if __name__ == "__main__":
    main()
