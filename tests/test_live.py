from dataclasses import dataclass
import hashlib
import hmac
import json
import time
import threading
import io
from urllib.parse import urlencode

import httpx
import pytest
from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage

from mirage.live import Server, Tunnel, ensure_cloudflared, validate_init_data
from mirage.model import Power


TOKEN = "12345678:" + "a" * 35


def signed(user=10, now=None, token=TOKEN):
    values = {"auth_date":str(int(time.time() if now is None else now)), "query_id":"example",
              "user":json.dumps({"id":user}, separators=(",", ":"))}
    check = "\n".join(f"{key}={value}" for key,value in sorted(values.items()))
    secret = hmac.digest(b"WebAppData", token.encode(), "sha256")
    values["hash"] = hmac.new(secret, check.encode(), "sha256").hexdigest()
    return urlencode(values)


def test_valid_telegram_owner_and_expired_or_tampered_data():
    validate_init_data(signed(now=1000), TOKEN, 10, now=1001)
    with pytest.raises(PermissionError):
        validate_init_data(signed(user=11, now=1000), TOKEN, 10, now=1001)
    with pytest.raises(PermissionError):
        validate_init_data(signed(now=1000), TOKEN, 10, now=5000)
    with pytest.raises(PermissionError):
        validate_init_data(signed(now=1000).replace("example", "tampered"), TOKEN, 10, now=1001)
    with pytest.raises(PermissionError):
        validate_init_data(signed(now=1000) + "&auth_date=1000", TOKEN, 10, now=1001)


def image_bytes():
    image = QImage(1200, 600, QImage.Format.Format_RGB32)
    image.fill(0xFF151618)
    output = QByteArray()
    buffer = QBuffer(output)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(output)


class Backend:
    def __init__(self):
        self.captures = []
        self.png = image_bytes()

    def instances(self):
        return [type("Instance", (), {"id":"ld:test:1", "name":"Farm", "power":Power.ONLINE})()]

    def screenshot(self, key):
        self.captures.append(key)
        return self.png


def test_real_http_rejects_unauthorized_frames_and_caches_owner_capture():
    backend = Backend()
    server = Server(backend, TOKEN, lambda: 10)
    url = server.start()
    try:
        with httpx.Client(base_url=url, trust_env=False, timeout=5) as client:
            assert client.get("/").status_code == 200
            assert client.get("/api/frame?instance=ld:test:1").status_code == 401
            assert backend.captures == []
            headers = {"X-Telegram-Init-Data": signed()}
            assert client.get("/api/instances", headers=headers).json()[0]["id"] == "ld:test:1"
            frame = client.get("/api/frame?instance=ld:test:1&quality=low", headers=headers)
            assert frame.status_code == 200
            decoded = QImage.fromData(frame.content)
            assert decoded.width() == 480 and decoded.height() == 240
            assert client.get("/api/frame?instance=ld:test:1&quality=low", headers=headers).content == frame.content
            assert backend.captures == ["ld:test:1"]
            assert client.get("/api/frame?instance=ld:other:1", headers=headers).status_code == 409
            assert client.post("/api/tap", headers=headers).status_code == 501
    finally:
        server.stop()


def test_cloudflare_download_is_verified_cached_and_atomic(tmp_path, monkeypatch):
    data = b"verified runtime"
    monkeypatch.setattr("mirage.live.CLOUDFLARED_SHA256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr("mirage.live.importlib.resources.files", lambda package: tmp_path / "not-bundled")
    calls = []
    def response(request):
        calls.append(request.url)
        return httpx.Response(200, content=data)
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        installed = ensure_cloudflared(tmp_path / "runtime", client=client)
        assert installed.read_bytes() == data
        assert ensure_cloudflared(tmp_path / "runtime", client=client) == installed
    assert len(calls) == 1
    assert not list((tmp_path / "runtime").glob("*.download"))


def test_unverified_cloudflare_does_not_replace_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("mirage.live.importlib.resources.files", lambda package: tmp_path / "not-bundled")
    destination = tmp_path / "cloudflared-2026.10.7.exe"
    destination.write_bytes(b"old file")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"wrong file"))) as client:
        with pytest.raises(ValueError, match="SHA-256"):
            ensure_cloudflared(tmp_path, client=client)
    assert destination.read_bytes() == b"old file"
    assert not list(tmp_path.glob("*.download"))


@pytest.mark.parametrize("registered", [False, True])
def test_tunnel_requires_registered_connection_not_just_public_url(tmp_path, monkeypatch, registered):
    binary = tmp_path / "cloudflared.exe"
    binary.write_bytes(b"runtime")
    monkeypatch.setattr("mirage.live.CLOUDFLARED_SHA256", hashlib.sha256(b"runtime").hexdigest())
    class Process:
        stderr = io.StringIO("https://example-test.trycloudflare.com\n" +
                             ("INF Registered tunnel connection\n" if registered else "ERR edge unreachable\n"))
        stopped = False
        def poll(self):
            return 0 if self.stopped else None
        def terminate(self):
            self.stopped = True
        def wait(self, timeout):
            return 0
    process = Process()
    monkeypatch.setattr("mirage.live.subprocess.Popen", lambda *args, **kwargs: process)
    tunnel = Tunnel()
    if registered:
        assert tunnel.start(binary, "http://127.0.0.1:1") == "https://example-test.trycloudflare.com"
        assert tunnel.connected
        tunnel.stop()
    else:
        with pytest.raises(RuntimeError, match="edge unreachable"):
            tunnel.start(binary, "http://127.0.0.1:1")
    assert process.stopped
    assert not tunnel.url
    assert not tunnel.connected
