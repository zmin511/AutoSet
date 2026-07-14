# Changelog

Формат: `MAJOR.MINOR.PATCH`


## 1.5.44

- Track Prep cards load immediately when a track is opened and are shown in a compact row below the overview waveform.
- Clicking a cue mark starts playback from that mark; clicking an OUTRO or EMERGENCY loop starts and repeats the loop until Play/CUE exits loop mode.
- Compact red delete controls and consistent English labels for IN, VOCAL, DROP, BREAK, OUT, OUTRO, and LOOP.
- Added regression coverage for Engine waveform-energy decoding and set-builder track loading.

## 1.5.43

- Split player/audio logic into app-player.js and kept waveform rendering/navigation in app-waveform.js.
- Synchronized project version references in documentation.
- No intended application behavior changes.
## 1.5.24

- Fixed the lower workspace frame alignment so the library browser stays visible on the left and the set/style panel stays pinned on the right.

## 1.5.23

- Split the lower workspace into two independent frames so the library/file browser stays isolated on the left and the set/style panel stays isolated on the right.

## 1.5.22

- Restored the lower workspace to the GitHub-style two-column layout with the browser on the left and controls, styles, output, and maintenance tools on the right.

## 1.5.20

- Fixed a regression in the overview-row refactor so the library, browser, lower panels, Track Prep, and Batch Suggest UI are visible again while keeping the compact top-row player layout.

## 1.5.19

- Refined the main workspace into a compact 4-block layout with aligned track, overview, zoom, and prep areas.
- Made the list play button and waveform loop labels clearer to avoid the stray question-mark look.

## 1.5.18

- Track Prep: added batch suggest preview for selected/visible tracks with accept, replace, open and clear controls.
- Track Prep: batch preview stays read-only until accepted into JSON.

## 1.5.17

- Track Prep: added auto-suggest preview for one selected track, with accept/clear controls and preview-only waveform overlays.
- Track Prep: suggested marks and loops stay outside saved JSON until accepted.

## 1.5.16

- Track Prep: overview seek now centers the zoom waveform while keeping Follow enabled, and zoom waveform supports tape-style drag navigation before playback.
- Track Prep: added hover time, snap-target preview, selected mark highlighting, loop-from-selected-mark creation, and waveform labels with mark/loop time ranges.

## 1.5.15

- Waveform: selecting a track now preloads audio metadata so overview/zoom seeking, scroll navigation and Track Prep marks work before pressing Play.
- Player: seek state, playhead and time display use Engine duration fallback while metadata is loading.

## 1.5.14

- Track Prep: added safe one-track export of saved manual marks and loops to Engine DJ PerformanceData quickCues/loops.
- Safety: export creates an Engine DB backup first, checks slot conflicts by default, and only overwrites target slots after explicit confirmation.

## 1.5.13

- Track Prep: добавлена ручная разметка MIX_IN/VOCAL_IN/DROP/BREAK/MIX_OUT/OUTRO и loop 4/8/16/32 поверх overview/zoom waveform.
- Track Prep: ручные marks/loops сохраняются во внутренние JSON-файлы `set_app/track_marks`, без записи в Engine DB и без изменения аудиофайлов.
- API: добавлены `GET/POST/DELETE /api/track_marks` для чтения, сохранения и удаления внутренней разметки.

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


