# Обычные исследования академии: состояние

2026-11-11, AutoBot_1, RoK1.1.12.20/PID18181/персонаж198113569. Исследование выполняется параллельно естественным таймерам сбора и строительства. Сценарий `research` пока не зарегистрирован.

Настоящий источник — **TechniqueData**, не ResearchData/TechnologyData/ScienceData (последние отсутствуют).

- TechniqueData.Datas содержит67 записей массива; индекс не равен ID технологии. Datas[1] — Id"103"/Type103/Level5; Datas[67] — Type233/Level4.
- ProcessSlotCount1.
- ResearchProcessNode[1] и Datas[29] указывают на одну запись **Type236/Id"236"/Level6**, StartTime1793835905510, EndTime1795047633119, TotalTime1472378698.
- ResearchFinishNode пуст.
- Значения TechniqueHandler: RESEARCH_STATE_NORMAL1, TRAINING2, FINISH3, FULL4. Эти константы не добавляют поле State в записи, где его нет.
- DatasUpdatedCount0 не означает отсутствия уже загруженных67 технологий.

Постоянный исследовательский слот уже занят существующей пользовательской технологией236. Её не отменяли и не ускоряли. Многодневный таймер не блокирует разработку других модулей. Для дальнейшего модуля нужны проверенные пути открытия академии/экономической и военной вкладок, текущая выбранная технология/уровень, её реальные требования/стоимость и квитанция нового обычного запуска в свободном слоте. Полный список Datas нужно индексировать по Type/Id, не позиции массива.

Свидетельства `%LOCALAPPDATA%\Temp\opencode`: `mirage-research-module-schema-20261111.json`, `mirage-research-roots-20261111.json`, `mirage-technique-state-schema-20261111.json`, `mirage-technique-queue-and-records-20261111.json`, `mirage-technique-current-queue-20261111.json`.
