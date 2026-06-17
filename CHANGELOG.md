# Changelog

Формат: `MAJOR.MINOR.PATCH`

## 1.5.12

- Tags: AutoSet now writes genre/style, BPM, key and rating changes back to supported audio files, not only to Engine DB.
- Tags: Added MP3/FLAC/M4A tag writing via mutagen with warnings for unsupported formats.
- UI: Tag write warnings are shown when Engine DB was updated but the audio file could not be updated.
- Waveform: Follow mode keeps overview seek from disabling follow behavior.

## 1.5.6

- Tags UI: галочка `С подпапками` перенесена в строку добавления тега.
- Selection: тег `Rus` стал отдельным допуском для русских треков; без выбранного `Rus` такие треки исключаются из подбора.

## 1.5.5

- Genres: одиночный жанр выбранного трека теперь можно вводить вручную, не только выбирать из списка.
- Genres: добавлен блок массового добавления, замены и удаления жанров для текущей папки.
- Genres: массовые операции могут работать с подпапками и пишут изменения в Engine DB и теги файлов.
- UI: название трека в списке сделано компактнее, поиск и блок обслуживания уплотнены.

## 1.5.4

- Engine playlist: создание плейлиста в Engine теперь использует `Track.id`, а не повторный поиск по пути файла.

## 1.5.3

- Branding: приложение и документация переименованы в `AutoSet`.
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
