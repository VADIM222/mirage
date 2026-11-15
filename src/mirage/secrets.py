from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import os
import re


def redact(text: str) -> str:
    return re.sub(r"(?<!\d)\d{5,20}:[A-Za-z0-9_-]{20,}", "<telegram-token>", str(text))


def _protect(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Хранилище токенов Mirage требует Windows DPAPI")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    input_blob = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output_blob = Blob()
    if decrypt:
        function = crypt32.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        success = function(ctypes.byref(input_blob), None, None, None, None, 1, ctypes.byref(output_blob))
    else:
        function = crypt32.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        success = function(ctypes.byref(input_blob), "Mirage", None, None, None, 1, ctypes.byref(output_blob))
    if not success:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output_blob.data, output_blob.size)
    finally:
        kernel32.LocalFree(output_blob.data)


def encrypt(text: str) -> str:
    return "dpapi:" + base64.b64encode(_protect(text.encode("utf-8"))).decode("ascii")


def decrypt(text: str) -> str:
    if not text.startswith("dpapi:"):
        raise ValueError("Неизвестный формат защищённого секрета")
    return _protect(base64.b64decode(text[6:], validate=True), decrypt=True).decode("utf-8")
