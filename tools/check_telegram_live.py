"""Real Bot API, real emulator capture and HTTPS tunnel check; no game input."""
import argparse
import hmac
import json
import os
import socket
from pathlib import Path
import threading
import time
from urllib.parse import urlencode
from urllib.parse import urlsplit
from unittest.mock import patch

import httpx
from PySide6.QtGui import QImage

from mirage.adb import Adb
from mirage.emulators import Discovery
from mirage.live import Server, Tunnel, ensure_cloudflared
from mirage.secrets import decrypt, redact
from mirage.storage import Store
from mirage.telegram import Api


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("instance")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-photo", action="store_true")
    args = parser.parse_args()
    store = Store(Path(os.environ["LOCALAPPDATA"]) / "Mirage" / "mirage.sqlite3")
    token = decrypt(store.preference("telegram_secret"))
    owner = store.preference("telegram_owner")
    if not owner:
        raise RuntimeError("Bind the owner in Mirage first")
    instance = next(i for i in Discovery().discover() if i.id == args.instance)
    adb = Adb(instance)
    adb.connect()
    class Backend:
        def instances(self):
            return [instance]
        def screenshot(self, key):
            if key != instance.id:
                raise ValueError("Unknown instance")
            return adb.screenshot()
    api = Api(token)
    server = Server(Backend(), token, lambda: owner)
    tunnel = Tunnel()
    result = {"instance":instance.id, "capture_only":True, "telegram":False, "photo":False, "https_frame":False}
    try:
        result["telegram"] = api.call("getMe").get("is_bot") is True
        if not args.skip_photo:
            capture = adb.screenshot()
            sent = api.call("sendPhoto", {"chat_id":owner,"caption":"Mirage · живая проверка снимка AutoBot_1 после обновления"}, capture)
            result["photo"] = bool(sent.get("photo"))
        else:
            result["photo"] = None
        binary = ensure_cloudflared(store.path.parent / "runtime")
        public = tunnel.start(binary, server.start())
        result["public_host"] = urlsplit(public).hostname
        result["tunnel_connected"] = tunnel.connected
        values = {"auth_date":str(int(time.time())), "user":json.dumps({"id":owner}, separators=(",", ":"))}
        check = "\n".join(f"{key}={value}" for key,value in sorted(values.items()))
        key = hmac.digest(b"WebAppData", token.encode(), "sha256")
        values["hash"] = hmac.new(key, check.encode(), "sha256").hexdigest()
        headers = {"X-Telegram-Init-Data":urlencode(values)}
        deadline = time.monotonic() + 90
        original_resolver = socket.getaddrinfo
        addresses = []
        def resolve(host, port, *values, **kwargs):
            if host in (result["public_host"], result["public_host"].encode()):
                return original_resolver(addresses[0], port, *values, **kwargs)
            return original_resolver(host, port, *values, **kwargs)
        with httpx.Client(timeout=10) as client:
            while True:
                try:
                    path = public + "/api/frame?" + urlencode({"instance":instance.id,"quality":"low"})
                    if addresses:
                        with patch("socket.getaddrinfo", resolve):
                            frame = client.get(path, headers=headers)
                    else:
                        frame = client.get(path, headers=headers)
                    frame.raise_for_status()
                    image = QImage.fromData(frame.content)
                    if image.isNull():
                        raise RuntimeError("HTTPS returned an invalid image")
                    result["https_frame"] = True
                    result["frame_size"] = [image.width(), image.height()]
                    if addresses:
                        with patch("socket.getaddrinfo", resolve):
                            result["anonymous_status"] = client.get(public + "/api/instances").status_code
                    else:
                        result["anonymous_status"] = client.get(public + "/api/instances").status_code
                    break
                except (httpx.HTTPError, RuntimeError) as error:
                    if not addresses and "getaddrinfo" in str(error):
                        answer = client.get("https://cloudflare-dns.com/dns-query", params={"name":result["public_host"],"type":"A"},
                                            headers={"Accept":"application/dns-json"})
                        addresses = [record["data"] for record in answer.json().get("Answer", []) if record.get("type") == 1]
                        result["dns_answer_status"] = answer.json().get("Status")
                        result["dns_address_count"] = len(addresses)
                        result["dns_resolution"] = "public Cloudflare DoH; Windows resolver failed"
                    if time.monotonic() >= deadline:
                        raise
                    threading.Event().wait(1)
        result["authentication"] = "locally signed owner initData over real HTTPS; Telegram client opening is a separate check"
    except Exception as error:
        result["error"] = redact(error)
        result["tunnel_logs"] = list(tunnel.logs)[-8:]
        if result.get("public_host"):
            try:
                answer = httpx.get("https://cloudflare-dns.com/dns-query", params={"name":result["public_host"],"type":"A"},
                                   headers={"Accept":"application/dns-json"}, timeout=10)
                result["public_dns_status"] = answer.json().get("Status")
                result["public_dns_records"] = len(answer.json().get("Answer", []))
            except Exception:
                result["public_dns_status"] = "unavailable"
    finally:
        tunnel.stop()
        server.stop()
        api.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    checks = ("telegram","https_frame") if args.skip_photo else ("telegram","photo","https_frame")
    raise SystemExit(0 if all(result[key] for key in checks) else 1)


if __name__ == "__main__":
    main()
