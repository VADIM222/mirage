from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
from typing import Any
from collections.abc import Callable

from .model import Profile


class Store:
    """Each operation owns its connection; GUI and worker threads never share one."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self.connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS profiles(instance_id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS presets(name TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP,
                    instance_id TEXT, level TEXT NOT NULL, message TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def profile(self, instance_id: str) -> Profile:
        with self.connect() as connection:
            row = connection.execute("SELECT body FROM profiles WHERE instance_id=?", (instance_id,)).fetchone()
        return Profile.from_dict(json.loads(row[0])) if row else Profile(instance_id)

    def save_profile(self, profile: Profile) -> None:
        body = json.dumps(profile.to_dict(), ensure_ascii=False, allow_nan=False)
        with self._lock, self.connect() as connection:
            connection.execute("INSERT INTO profiles VALUES (?,?) ON CONFLICT(instance_id) DO UPDATE SET body=excluded.body",
                                (profile.instance_id, body))

    def update_profile(self, instance_id: str, change: Callable[[Profile], None]) -> Profile:
        """Apply one UI edit to the latest profile without overwriting remote edits."""
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT body FROM profiles WHERE instance_id=?", (instance_id,)).fetchone()
            profile = Profile.from_dict(json.loads(row[0])) if row else Profile(instance_id)
            change(profile)
            body = json.dumps(profile.to_dict(), ensure_ascii=False, allow_nan=False)
            connection.execute("INSERT INTO profiles VALUES (?,?) ON CONFLICT(instance_id) DO UPDATE SET body=excluded.body",
                               (instance_id, body))
        return profile

    def preference(self, key: str, default=None) -> Any:
        with self.connect() as connection:
            row = connection.execute("SELECT body FROM preferences WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_preference(self, key: str, value: Any) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("INSERT INTO preferences VALUES (?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body",
                                (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))

    def update_preference(self, key: str, change: Callable, default=None):
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT body FROM preferences WHERE key=?", (key,)).fetchone()
            value = change(json.loads(row[0]) if row else default)
            connection.execute("INSERT INTO preferences VALUES (?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body",
                               (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))
        return value

    def copy_profile(self, source: str, destinations: list[str]) -> None:
        body = self.profile(source).to_dict()
        with self._lock, self.connect() as connection:
            for destination in dict.fromkeys(destinations):
                target = self.profile(destination)
                new = Profile.from_dict({**body, "instance_id": destination, "account_name": target.account_name,
                                         "manual_run": False, "manual_pause": target.manual_pause})
                connection.execute("INSERT INTO profiles VALUES (?,?) ON CONFLICT(instance_id) DO UPDATE SET body=excluded.body",
                                    (destination, json.dumps(new.to_dict(), ensure_ascii=False)))

    def presets(self) -> list[str]:
        with self.connect() as connection:
            return [row[0] for row in connection.execute("SELECT name FROM presets ORDER BY name COLLATE NOCASE")]

    def save_preset(self, name: str, profile: Profile) -> None:
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("Название пресета должно содержать от 1 до 80 символов")
        values = profile.to_dict()
        body = {key: values[key] for key in ("tasks", "slots", "schedule_enabled")}
        with self._lock, self.connect() as connection:
            connection.execute("INSERT INTO presets VALUES (?,?) ON CONFLICT(name) DO UPDATE SET body=excluded.body",
                               (name, json.dumps(body, ensure_ascii=False, allow_nan=False)))

    def delete_preset(self, name: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("DELETE FROM presets WHERE name=?", (name,))

    def apply_preset(self, name: str, destinations: list[str]) -> None:
        with self._lock, self.connect() as connection:
            row = connection.execute("SELECT body FROM presets WHERE name=?", (name,)).fetchone()
            if row is None:
                raise ValueError("Пресет больше не существует")
            template = json.loads(row[0])
            for key in dict.fromkeys(destinations):
                row = connection.execute("SELECT body FROM profiles WHERE instance_id=?", (key,)).fetchone()
                target = json.loads(row[0]) if row else Profile(key).to_dict()
                profile = Profile.from_dict({**target, **template, "manual_run": False, "manual_pause": True})
                connection.execute("INSERT INTO profiles VALUES (?,?) ON CONFLICT(instance_id) DO UPDATE SET body=excluded.body",
                                   (key, json.dumps(profile.to_dict(), ensure_ascii=False)))

    def event(self, instance_id: str | None, level: str, message: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("INSERT INTO events(instance_id,level,message) VALUES (?,?,?)", (instance_id, level, message))
            connection.execute("DELETE FROM events WHERE id <= (SELECT COALESCE(MAX(id),0)-5000 FROM events)")

    def events(self, limit: int = 150) -> list[tuple]:
        with self.connect() as connection:
            return connection.execute("SELECT id,created,instance_id,level,message FROM events ORDER BY id DESC LIMIT ?",
                                      (min(max(int(limit), 1), 5000),)).fetchall()[::-1]

    def export_profiles(self) -> dict:
        with self.connect() as connection:
            rows = connection.execute("SELECT body FROM profiles ORDER BY instance_id").fetchall()
            presets = [{"name":name, "settings":json.loads(body)} for name,body in
                       connection.execute("SELECT name,body FROM presets ORDER BY name")]
        profiles = []
        for (body,) in rows:
            value = json.loads(body)
            value["manual_run"] = False
            profiles.append(value)
        return {"format": "mirage-profiles", "version": 1, "profiles": profiles, "presets":presets}

    def import_profiles(self, document: dict) -> None:
        if document.get("format") != "mirage-profiles" or document.get("version") != 1:
            raise ValueError("Неподдерживаемый формат конфигурации")
        profiles = [Profile.from_dict({**value, "manual_run": False}) for value in document["profiles"]]
        if len({p.instance_id for p in profiles}) != len(profiles):
            raise ValueError("Дублирующиеся профили")
        presets = []
        for value in document.get("presets", []):
            name, settings = value["name"], value["settings"]
            if (not isinstance(name, str) or not name.strip() or len(name) > 80
                    or not isinstance(settings, dict) or set(settings) != {"tasks","slots","schedule_enabled"}):
                raise ValueError("Некорректный пресет в конфигурации")
            Profile.from_dict({"instance_id":"preset", **settings})
            presets.append((name.strip(), json.dumps(settings, ensure_ascii=False, allow_nan=False)))
        if len({name for name,body in presets}) != len(presets):
            raise ValueError("Дублирующиеся пресеты")
        with self._lock, self.connect() as connection:
            for profile in profiles:
                connection.execute("INSERT INTO profiles VALUES (?,?) ON CONFLICT(instance_id) DO UPDATE SET body=excluded.body",
                                   (profile.instance_id, json.dumps(profile.to_dict(), ensure_ascii=False)))
            connection.executemany("INSERT INTO presets VALUES (?,?) ON CONFLICT(name) DO UPDATE SET body=excluded.body", presets)
