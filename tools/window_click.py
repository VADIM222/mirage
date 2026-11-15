"""Send a diagnostic click to one named application window, never the desktop."""
import argparse
import ctypes
from ctypes import wintypes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("title")
    parser.add_argument("x", type=float)
    parser.add_argument("y", type=float)
    parser.add_argument("--physical", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.x <= 1 or not 0 <= args.y <= 1:
        parser.error("Coordinates must be fractions of the client area")
    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    hwnd = user32.FindWindowW(None, args.title)
    if not hwnd:
        raise SystemExit("Window not found")
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    x, y = int(rect.right * args.x), int(rect.bottom * args.y)
    if args.physical:
        previous = wintypes.POINT()
        point = wintypes.POINT(x, y)
        user32.GetCursorPos(ctypes.byref(previous))
        user32.SetForegroundWindow(hwnd)
        user32.ClientToScreen(hwnd, ctypes.byref(point))
        user32.SetCursorPos(point.x, point.y)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
    else:
        user32.PostMessageW(hwnd, 0x0200, 0, (y << 16) | x)
        user32.PostMessageW(hwnd, 0x0201, 1, (y << 16) | x)
        user32.PostMessageW(hwnd, 0x0202, 0, (y << 16) | x)
    print(f"Click queued to {args.title!r} at {x},{y}")


if __name__ == "__main__":
    main()
