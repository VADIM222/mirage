# Сторонние инструменты

Код Mirage написан самостоятельно. Общедоступные зависимости не являются реализациями Whale или Nexus:

- Python — https://www.python.org/ (PSF).
- Qt / PySide6 6.12.0 — https://www.qt.io/qt-for-python (LGPL/GPL/commercial, согласно поставке).
- Frida 17.26.2 — https://frida.re/ и https://github.com/frida/frida (лицензии проекта Frida).
- HTTPX 0.28.1 — https://www.python-httpx.org/ (BSD-3-Clause).
- PyInstaller — https://pyinstaller.org/ (GPL с исключением для создаваемых приложений).
- Android Debug Bridge — инструмент установленного эмулятора либо официальных Android Platform Tools.
- Cloudflared 2026.10.7 — https://github.com/cloudflare/cloudflared (Apache-2.0), устанавливается отдельно для Live; URL и SHA-256 закреплены в `src/mirage/live.py`.

Android Frida Server устанавливается отдельно. Закреплённые URL и SHA-256 находятся в `src/mirage/runtime.py`. При исследовании использовался уже установленный общедоступный Frida runtime 17.26.2; версия и SHA-256 сверены с манифестом имеющейся поставки. Независимое скачивание GitHub-архива в этой среде завершилось сетевым тайм-аутом. Проприетарные модули, игровые сценарии, исходники и интерфейсные ресурсы Whale/Nexus в проект не переносились.
