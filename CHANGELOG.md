# Changelog

Формат: `MAJOR.MINOR.PATCH`

## 1.5.3

- Energy: звездочки в списке треков показывают расчетную waveform-энергию 1..5.
- Energy: добавлена кнопка записи расчетной энергии в `Track.rating` Engine DJ для текущей папки.
- Energy: добавлена отдельная кнопка записи звезд для всей медиатеки `Music`.
- Energy: запись `Track.rating` приведена к шкале Engine DJ `20/40/60/80/100`.
- UI: выбранный трек, плеер и waveform вынесены в единую верхнюю панель.
- UI: выровнены основные колонки библиотеки и панели сборки.
- Camelot: подсказка `±N` показывает только входящие числа Camelot.

## 1.5.2

- Engine-like waveform: цветная overview‑вейвформа из `PerformanceData.overviewWaveFormData`.
- Cue/Loop: чтение `PerformanceData.quickCues` / `PerformanceData.loops`, отображение маркеров и времени.
- Плеер: скраб по waveform, playhead, компактный UI.
- Сборка сета: добавлена “энергия” трека из waveform и базовая energy‑кривая при подборе.
- Camelot: `±N` считается по числам круга в обе стороны; A/B не увеличивает расстояние.
