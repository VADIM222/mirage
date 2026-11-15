"""Offline presentation translation; stored events and engine state stay canonical."""
from functools import lru_cache
import importlib.resources
import json
import re


LANGUAGES = (('ru', 'Русский'), ('en', 'English'))
_language = 'ru'
CYRILLIC = re.compile(r'[\u0400-\u04ff]')
_PATHS = re.compile(r'''((?:["'](?:[A-Za-z]:[\\/]|\\\\)[^\r\n]*?["'])|(?:(?:[A-Za-z]:[\\/]|\\\\)[^\s,;<>"']+))''')


def normalize_language(value):
    return value if value in ('ru', 'en') else 'ru'


def set_language(language):
    global _language
    _language = normalize_language(language)


def get_language():
    return _language


@lru_cache(maxsize=1)
def catalog():
    return json.loads(importlib.resources.files('mirage').joinpath('locales/en.json').read_text(encoding='utf8'))


@lru_cache(maxsize=1)
def _phrases():
    # Longest source first also covers historical f-strings and composed errors.
    # Cyrillic boundaries prevent a short label from modifying an unknown name.
    phrases = []
    for source in sorted(catalog(), key=len, reverse=True):
        pattern = re.escape(source)
        if CYRILLIC.fullmatch(source[0]):
            pattern = r'(?<![\u0400-\u04ff])' + pattern
        if CYRILLIC.fullmatch(source[-1]):
            pattern += r'(?![\u0400-\u04ff])'
        phrases.append(pattern)
    return re.compile('|'.join(phrases))


class Verbatim(str):
    """User-owned names, paths and other values that must not be translated."""


def translate(text, language=None):
    if not isinstance(text, str) or isinstance(text, Verbatim):
        return text
    if normalize_language(language or _language) == 'ru' or not CYRILLIC.search(text):
        return text
    direct = catalog().get(text)
    if direct is not None:
        return direct
    return ''.join(part if index % 2 else _phrases().sub(lambda match: catalog()[match.group(0)], part)
                   for index, part in enumerate(_PATHS.split(text)))


def language_for(store):
    return normalize_language(store.preference('language', 'ru'))
