# Лечение: источники состояния

Исследование 2026-11-09, RoK1.1.12.20/PID23282. Сценарий пока не зарегистрирован.

- `HealingData.HealingStatusList` и `HealingCDStatus` — пустые таблицы.
- Раненые находятся в записях `TrainingData.UnitList`: поля `unitId`, `unitCount`, `hurt`, `badHurt`, `maxCount`. Позиция записи не равна unitId: вторая запись содержит unitId3, третья —115. Нельзя индексировать эту таблицу ID войск.
- У всех16 прочитанных записей `hurt=0` и `badHurt=0`; положительный цикл лечения сейчас недоступен.
- Дополнительные виды войск: `TrainingData.LowUnitList` содержит одну запись unitId4 с нулевыми hurt/badHurt/unitCount/maxCount; `SpotlightUnitList` пуст. Раненых в этих списках также не обнаружено (`mirage-healing-extra-unit-lists.json`, `mirage-healing-low-unit-injuries.json`).
- `HealingHandler.GetInjuredUnits` захватывает таблицу порядка типов войск (1,2,3,4,−1,−2), а не таблицу ранений. Методы не вызывались.
- Для будущего цикла нужны реальные раненые, прочитанная стоимость и вместимость, выбранный госпиталь, подтверждение количества/резервов, таймера и результата; ускорения и гемы по умолчанию исключены.

## Маршрут госпиталя, 2026-11-11

Повторно подтверждены16 обычных записей и дополнительные LowUnitList/SpotlightUnitList без раненых. HealingStatusList/HealingCDStatus пусты.

- Общее построение города довело камеру к госпиталю id20/type14/Level25. Меню выбора содержит строго `btn_CityPopUpInfo`, `btn_FunctionHospital`. В проверенной геометрии госпиталь открывается(514,345).
- Активное окно `CityUIHospital`, buildId="20"/buildType14, panelState="disable". injuredUnits пуст, normalUnitList/healingUnitList=nil. UsePiety=false/PietyNum0/m_pietyEnabled=false. Форма явно сообщает отсутствие раненых, вместимость364500 обычных и50000 зоны таранов.
- Закрытие(819,62), затем общий сброс выбора вернули CITY_HUD, гемы64835 и остальные валюты сохранены. Кнопки лечения/мгновенного завершения не нажимались.
- `HealingHandler.GetHealingCost` и GetHealingStatus имеют общую захваченную таблицу; методы не вызывались. Для положительного цикла по-прежнему нужны раненые и состояние реальной формы/стоимости/очереди.

Свидетельства: `mirage-hospital-building-selection-20261111.json/.png`, `mirage-hospital-empty-form-20261111.json/.png`, `mirage-hospital-empty-data-20261111.json`, `mirage-hospital-empty-return-20261111.json` в `%LOCALAPPDATA%\Temp\opencode`. Сценарий лечения пока не зарегистрирован.

Свидетельства: `%TEMP%\opencode\mirage-healing-injuries-all-units.json`, `mirage-healing-training-data-roots.json`, `mirage-healing-unit-data-state.json`.
