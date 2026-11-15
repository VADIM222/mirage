from __future__ import annotations

import hashlib
from collections import deque
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.resources
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid
from urllib.parse import parse_qsl, urlsplit

import httpx

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage
from .i18n import get_language, translate


CLOUDFLARED_SHA256 = "2493dbc168923bb3e59e5e7716f71deced92992eea9acd6e9d74f84ac7751343"
CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/download/2026.10.7/cloudflared-windows-amd64.exe"


def ensure_cloudflared(directory: Path, cancelled: threading.Event | None = None,
                       progress=lambda message: None, *, client: httpx.Client | None = None) -> Path:
    """Install a verified runtime automatically into Mirage's own writable cache."""
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "cloudflared-2026.10.7.exe"
    def verified(path):
        if not path.is_file():
            return False
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == CLOUDFLARED_SHA256
    if verified(destination):
        return destination
    temporary = directory / ("cloudflared-" + uuid.uuid4().hex + ".download")
    owned_client = client is None
    connection = client
    try:
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("Установка Cloudflare отменена")
        bundled = importlib.resources.files("mirage").joinpath("vendor/cloudflared.exe")
        if bundled.is_file():
            progress("Подготовка Cloudflare…")
            with bundled.open("rb") as source, temporary.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    if cancelled is not None and cancelled.is_set():
                        raise RuntimeError("Установка Cloudflare отменена")
                    output.write(chunk)
        else:
            progress("Загрузка Cloudflare…")
            connection = connection or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30, connect=10))
            started = time.monotonic()
            size = 0
            with connection.stream("GET", CLOUDFLARED_URL, follow_redirects=True) as response:
                response.raise_for_status()
                with temporary.open("wb") as output:
                    for chunk in response.iter_bytes(1024 * 1024):
                        if cancelled is not None and cancelled.is_set():
                            raise RuntimeError("Установка Cloudflare отменена")
                        size += len(chunk)
                        if size > 150 * 1024 * 1024 or time.monotonic() - started > 120:
                            raise RuntimeError("Превышено время или размер загрузки Cloudflare")
                        output.write(chunk)
        if not verified(temporary):
            raise ValueError("Загруженный Cloudflare не прошёл проверку SHA-256")
        temporary.replace(destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)
        if owned_client and connection is not None:
            connection.close()


def validate_init_data(data: str, token: str, owner: int, *, now: float | None = None) -> None:
    try:
        pairs = parse_qsl(data, strict_parsing=True, max_num_fields=20)
        fields = dict(pairs)
        if len(pairs) != len(fields) or len(data) > 16384:
            raise ValueError
        supplied = fields.pop("hash")
        if not re.fullmatch(r"[0-9a-f]{64}", supplied):
            raise ValueError
        check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        key = hmac.digest(b"WebAppData", token.encode(), "sha256")
        expected = hmac.new(key, check.encode(), "sha256").hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise ValueError
        user = json.loads(fields["user"])
        age = (time.time() if now is None else now) - int(fields["auth_date"])
        if type(user.get("id")) is not int or user["id"] != owner or not -30 <= age <= 3600:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise PermissionError("Откройте Live из личного чата владельца Mirage заново") from None


class Server:
    """Read-only screen viewer. The HTTP interface has no game-input endpoints."""

    def __init__(self, backend, token: str, owner):
        self.backend, self.token, self.owner = backend, token, owner
        self.http: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.url = ""
        self._lock = threading.Lock()
        self._frames: dict[tuple[str, str], tuple[float, bytes, str]] = {}

    def frame(self, instance, quality):
        if quality not in ("low", "standard", "original"):
            raise ValueError("Неизвестное качество изображения")
        with self._lock:
            key = (instance, quality)
            cached = self._frames.get(key)
            if cached and time.monotonic() - cached[0] < 1:
                return cached[1:]
            data = self.backend.screenshot(instance)
            mime = "image/png"
            if quality != "original":
                image = QImage.fromData(data, "PNG")
                if image.isNull():
                    raise ValueError("Android вернул некорректное изображение")
                width = 480 if quality == "low" else 960
                if image.width() > width:
                    image = image.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
                output = QByteArray()
                buffer = QBuffer(output)
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                if not image.save(buffer, "JPEG", 55 if quality == "low" else 80):
                    raise ValueError("Не удалось подготовить кадр Live")
                data, mime = bytes(output), "image/jpeg"
            if len(self._frames) >= 6:
                self._frames.clear()
            self._frames[key] = (time.monotonic(), data, mime)
            return data, mime

    def start(self):
        if self.http is not None:
            raise RuntimeError("Live уже включён")
        service = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def reply(self, status, data, mime="application/json; charset=utf-8"):
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                if parsed.path == "/":
                    text = importlib.resources.files("mirage").joinpath("assets/live.html").read_text(encoding='utf8')
                    language = get_language()
                    data = translate(text, language).replace('<html lang="ru">', f'<html lang="{language}">').encode('utf8')
                    self.reply(200, data, "text/html; charset=utf-8")
                    return
                try:
                    owner = service.owner()
                    if type(owner) is not int:
                        raise PermissionError("Владелец Telegram ещё не привязан")
                    validate_init_data(self.headers.get("X-Telegram-Init-Data", ""), service.token, owner)
                    if parsed.path == "/api/instances":
                        data = [{"id": i.id, "name": i.name, "power": str(i.power)} for i in service.backend.instances()]
                        self.reply(200, json.dumps(data, ensure_ascii=False).encode())
                    elif parsed.path == "/api/frame":
                        query = dict(parse_qsl(parsed.query, max_num_fields=5))
                        if query.get("instance") not in {i.id for i in service.backend.instances()}:
                            raise ValueError("Неизвестный экземпляр")
                        data, mime = service.frame(query["instance"], query.get("quality", "standard"))
                        self.reply(200, data, mime)
                    else:
                        self.reply(404, b'{"error":"not found"}')
                except PermissionError as error:
                    self.reply(401, json.dumps({"error": translate(str(error))}, ensure_ascii=False).encode())
                except (ValueError, RuntimeError, OSError, StopIteration) as error:
                    self.reply(409, json.dumps({"error": translate(str(error))}, ensure_ascii=False).encode())

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http.daemon_threads = True
        self.http.timeout = 10
        self.thread = threading.Thread(target=self.http.serve_forever, name="mirage-live", daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        return self.url

    def stop(self):
        if self.http:
            self.http.shutdown()
            self.http.server_close()
            self.http = None
        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None
        self._frames.clear()
        self.url = ""


class Tunnel:
    def __init__(self):
        self.process = None
        self.url = ""
        self.connected = False
        self.logs = deque(maxlen=30)

    def start(self, binary: Path, local_url: str):
        if self.process is not None:
            raise RuntimeError("Туннель Live уже запущен")
        with binary.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != CLOUDFLARED_SHA256:
            raise ValueError("Не подтверждён SHA-256 cloudflared 2026.10.7")
        ready = threading.Event()
        self.process = subprocess.Popen([str(binary), "tunnel", "--no-autoupdate", "--url", local_url],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                        encoding="utf-8", errors="replace",
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        process = self.process
        def read():
            for line in process.stderr:
                self.logs.append(line.strip())
                match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if match:
                    self.url = match.group(0)
                if "Registered tunnel connection" in line:
                    self.connected = True
                if self.url and self.connected:
                    ready.set()
            ready.set()
        threading.Thread(target=read, name="mirage-tunnel", daemon=True).start()
        if not ready.wait(45) or not self.url or not self.connected or process.poll() is not None:
            failure = next((line for line in reversed(self.logs) if "ERR" in line), "Cloudflare не подтвердил соединение")
            self.stop()
            raise RuntimeError("Не удалось включить HTTPS Live: " + failure[:400])
        return self.url

    def stop(self):
        process, self.process = self.process, None
        if process:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.stderr:
                process.stderr.close()
        self.url = ""
        self.connected = False
