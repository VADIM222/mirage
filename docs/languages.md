# Русский / English

## Выбор языка / Language selection

**Настройки → Язык интерфейса → Русский / English.** Выбор сохраняется сразу и применяется без перезапуска. В Telegram тот же выбор доступен из главного меню. Изменение через Telegram отображается в Desktop в течение секунды.

**Settings → Interface Language → Русский / English.** Saved immediately and applied without restarting. Telegram exposes the same choice in its main menu. Desktop picks up a Telegram language change within one second.

## Покрытие / Coverage

- Навигация, полный список44 функций и группы, готовность, настройки всех задач и пояснения.
- Таблицы приоритетов исследований, ресурсы, здания, материалы, слоты и диалоги.
- Статусы эмуляторов/автоматизации, сообщения движка, ошибки и текущий/сохранённый журнал.
- Меню, клавиатуры, ответы, ошибки и уведомления Telegram.
- Mirage Live: текст страницы и ошибок на языке Mirage при открытии/перезагрузке.
- All navigation, the complete 44-task list, groups, readiness, task settings and descriptions.
- Research priorities, resources, buildings, materials, time slots and dialogs.
- Emulator/automation statuses, engine messages, errors and saved/current event logs.
- Telegram menus, keyboards, replies, errors and notifications.
- Mirage Live page text and errors, using Mirage's language when opened/reloaded.

Перевод локальный: внешние сервисы и доступ к сети не нужны. Каталог `src/mirage/locales/en.json` включает все1421 исходных сообщения и дополнительные тексты Live/исторического журнала. Автоматическая проверка покрытия обнаруживает новые непереведённые строки приложения.

Translation is offline and does not require external services or network access. `src/mirage/locales/en.json` covers all 1,421 original source messages plus Live and historical-log text. A source-coverage check detects new untranslated application strings.

Исходные записи SQLite не переписываются. Имена пользователя/эмуляторов/пресетов, пути и идентификаторы сохраняются. Названия командиров, прочитанные из игрового каталога, показываются как в каталоге. Язык самой игры не меняется. Строки сторонних библиотек и неизвестные сообщения внешних программ показываются в исходном виде.

SQLite event records are not rewritten. User/emulator/preset names, paths and identifiers are preserved. Commander names read from the game's roster retain their roster spelling. The game's language is not changed. External tools and libraries may report their own messages in their original language.

Смена языка меняет только представление и настройку `language`: она не запускает/останавливает игровые задачи, не меняет расписания, настройки сбора ресурсов, владельца армии или ручной «Стоп».

Changing language affects presentation and the `language` preference only. It does not start/stop game tasks or change schedules, resource-gathering settings, army ownership or manual Stop.
