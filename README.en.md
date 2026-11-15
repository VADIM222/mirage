# Mirage

Independent Windows desktop automation workspace for Rise of Kingdoms, built with Python, PySide6 and SQLite. BlueStacks and LDPlayer are supported. Game state is read from the game process; Android input uses ADB.

[Русский](README.md) · [Language support](docs/languages.md) · [Verification history (Russian)](docs/verification.md)

**Private GitHub:** [VADIM222/mirage](https://github.com/VADIM222/mirage) · [Windows releases](https://github.com/VADIM222/mirage/releases) · [Builds and checks](https://github.com/VADIM222/mirage/actions). Repository access is required to view or download private releases.

## Run

Launch `Mirage.exe` from the complete Windows release folder. Keep the `_internal` directory beside the executable.

Choose **Settings → Interface Language → English** or **Русский**. The choice is saved automatically and applies immediately to the entire task list, task settings, research priority tables, statuses, dialogs and event log. Telegram uses the same preference and has a language menu. Mirage Live uses the selected language when opened or reloaded.

## Current capabilities

- Local emulator management, independent task profiles, schedules, optional explicit rotation and automatic saving.
- Telegram control and owner-authenticated, read-only Live screenshots.
- 26 of 44 task scenarios are registered. Registered scenarios retain their version, screen and state requirements; the complete Whale feature set is not implemented yet.
- Normal barbarian farming and separate barbarian chaining, with owned-army reuse and persistent sessions. Chaining surveys existing NPCs using the wide Resources map view; normal resource gathering keeps its regular in-game search.
- Building/research prerequisites and configurable research priorities, troop training/collection, alliance donations, normal materials, city resources, scouting, villages, caves and selected rewards.
- Some tasks remain partial, including the new-player tutorial and VIP Shop. Exact historical results and limitations are documented in `docs/verification.md`.

Selecting a language does not start tasks, change game language, modify task settings or clear the manual Stop. Player/emulator names, paths, task IDs, commander IDs and Telegram callback data remain unchanged. Translation is offline. Stored log records are retained in their original form and translated only for display.

## Development

Use Python 3.12 or later (the packaged Windows build uses Python 3.14):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q
.\tools\build.ps1
```

Runtime profiles and protected Telegram credentials are stored outside the source tree under `%LOCALAPPDATA%\Mirage`. Build outputs, runtime databases, tokens and local research diagnostics are excluded from Git. See `THIRD_PARTY.md` for third-party components.
