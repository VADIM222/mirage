# Люцернские свитки: текущее состояние

2026-11-11, AutoBot_1, RoK1.1.12.20/PID18181/персонаж198113569. Сценарий `lucerne` зарегистрирован. Ниже сохранены исходные наблюдения, затем результаты реализации.

- `BattlePassData.m_TimeInfo`: SeasonId62, StartTime1791417600000, EndTime1794441600000, WeekBaseStartTime1791158400000.
- `m_LevelInfo`: Level2/Exp10; `m_nPayType=1` совпадает с PayTypeFree1. RewardTypeFree1, RewardTypePay2, RewardTypeAll0. `m_nMaxLootLevel=0`.
- В `m_aRewardStatus`51 запись. У уровней1/2 `FreeGet=true`, `PayGet=false`: эти бесплатные награды уже получены. Присутствуют отдельные FreeLoot/PayLoot и PayCondLocked; нельзя принимать доступность платной дорожки за бесплатную награду.
- `m_nDailyStatus=1`, константы DailyStatusFinished1/DailyStatusClaimed2/DailyStatusInvalid0. Значение допускает дальнейшее исследование ежедневного опыта, но само по себе не разрешает неподтверждённую кнопку.
- `m_bForceGuideIcon=true`, EnableFlag=true. ShowEntrance/ShowBuildingGuideIcon исследовались только как источники захваченных данных; игровые обработчики не вызывались.
- В фактическом списке Event Center из18 строк входа Lucerne/BattlePass нет. Список содержит заголовки TagId и записи EventIdx/Data; индексы не соответствуют EventId и экранным строкам после прокрутки.
- Верхние значки текущего HUD нельзя переносить из старых снимков: (796,65) открывает KVKChooseScript, (606,65) — WelcomeBackEventsMainPage, (860,65) — GVGGlobalSchedule, (928,65) — DlcHeroPopUp. Исследовательские вызовы с ожиданием BattlePass завершились неподтверждённым переходом; ни один не считается успешным маршрутом Lucerne. Все открытые окна закрыты известными Back/Close; CITY_HUD/PID/персонаж/гемы64835 сохранены.

## Реализация и положительное получение

Настоящий вход: торговый пост82/type19, `img_BattlePassHudIcon`, кнопка(439,354). Вкладки читаются read-only из закрытых captures SwitchTapTop/1/6, SwitchTapMission/1/4, SwitchTapWeek/1/1. Конфиги Score — GetMissionCfg up2/season иup3/week, константы — GetConstCfg up1; игровые обработчики и Unity-getter не вызываются.

- Ежедневный опыт+50 подтверждён Engine6.76с.
- Всего15 недельных и1 сезонное испытание получены по участкам. Первый mission-цикл получил2 и остановился на новом LevelUp; исправленный resume84.13с закрыл известное окно и получил оставшиеся14. Итог Level14/Exp0; валюты и инвентарь при опыте сохранены.
- Claim All выдал12 бесплатных призов уровней3–14, прирост9 типов предметов. Первоначальная квитанция отвергла PayGet nil→false, исправленная отдельно подтвердила сохранённый реальный переход. Resume8.51с закрыл награду и вернул город, без нового получения.
- Известные окна: LevelUp Close(619,436), Reward OK(480,443). RewardRows читаются из OnItemEnter capture2/2 и сверяются с уже полученными бесплатными призами/активами перед закрытием.
- TaskStatus−1 готов,−2 получен,≥0 прогресс. Игра пересортировывает задачи; квитанция ищет TaskID внутри нужной недели.
- `max_claims`1–32 — лимит опыта за проверку, Desktop/Telegram. Платный пропуск/покупка уровней не поддерживаются. По достижении лимита бесплатные призы оставляются следующей проверке.

Свидетельства новых Engine-участков перечислены в [verification.md](verification.md). Полный тестовый набор649 прошёл, включая маршрут/восстановление/отмену и редакторы.

Свидетельства в `%LOCALAPPDATA%\Temp\opencode`: `mirage-lucerne-state-current-20261111.json`, `mirage-battlepass-entrance-binding-20261111.json`, `mirage-event-sidebar-all-records-20261111.json`, `mirage-lucerne-entry-current-20261111.png`, `mirage-lucerne-direct-entry-20261111.png`, `mirage-lucerne-trophy-entry-20261111.png`, `mirage-hud-expanded-icons-20261111.png`.
