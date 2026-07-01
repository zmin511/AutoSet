# AutoSet: сводка проекта на 2026-06-30

## Идентификация аудита

- Название проекта: `AutoSet`.
- Основание для названия: `APP_NAME = "AutoSet"` в `F:\AutoSet\set_app\set_app.py`, README и GitHub remote `https://github.com/zmin511/AutoSet.git`.
- Текущая дата аудита: `2026-06-30`.
- Текущий Codex project label: `Music`, путь `F:\Music`; это рабочая музыкальная библиотека и текущий workspace, но основной код проекта находится в `F:\AutoSet`.
- Предыдущий Markdown-аудит найден: да, комплект от `2026-06-17`.
- Где найден предыдущий аудит: `F:\AutoSet\install\AutoSet_*_2026-06-17.md` и `F:\AutoSet\install\AutoSet_AUDIT_2026-06-17.zip`, а также чат Codex `019ed57c-81b3-7191-8257-1b785a70d1ec`.
- В корне `F:\Music` предыдущие Markdown-файлы аудита не найдены. Это важно: предыдущий чат писал, что создавал их в `F:\Music`, но в текущей файловой картине они лежат в `F:\AutoSet\install` как untracked-файлы.

## Краткое описание проекта

`AutoSet` - локальное portable-приложение для Denon Engine DJ. Оно читает SQLite-базу Engine DJ, показывает библиотеку, waveform, cue/loop, строит DJ-сеты по BPM, Camelot, жанрам/стилям и энергии, создает локальные папки сетов и Engine-плейлисты, управляет жанрами/тегами, а после аудита `2026-06-17` получило большой блок Track Prep: ручные и автоматические cue/loop-разметки с JSON-хранением и экспортом в Engine DJ.

## Текущий статус

- Актуальная версия по файлам: `1.5.24`.
- Основной код: `F:\AutoSet`.
- Основная медиатека: `F:\Music`.
- Основная Engine DB: `F:\Engine Library\Database2\m.db`.
- GitHub remote: `https://github.com/zmin511/AutoSet.git`.
- Последний коммит в локальном `F:\AutoSet`: `5c144a2 Fix missing library frame in lower layout`.
- Рабочее дерево `F:\AutoSet` не чистое: изменены `.gitignore`, `set_app/index.html`, `set_app/run_windows.cmd`, `set_app/set_app.py`; есть untracked `debug/`, `install/AutoSet_*_2026-06-17.*`, `set_app/index1.html`, `set_app/set_app1.py`.
- Поэтому текущий статус: релизная линия дошла до `1.5.24`, но поверх нее есть незакоммиченный рабочий слой, особенно по audio/WebAudio/media playback.

## Что уже реализовано

- Portable Python HTTP-сервер и браузерный UI.
- Выбор музыкальной библиотеки и Engine DB.
- Чтение Engine DB: `Track`, `PerformanceData`, `Playlist`, `PlaylistEntity`.
- Построение сетов по BPM, Camelot, жанру/стилю, длительности, битрейту и примерной энергии.
- Сохранение готовых сетов в `F:\Music\Sets`.
- Создание Engine-плейлистов по существующим `Track.id`.
- Waveform overview/zoom, beat-grid, cues, loops, playhead, Follow mode.
- Редактирование жанров/стилей и запись в Engine DB.
- Запись тегов в MP3/FLAC/M4A через `mutagen`, с предупреждениями для неподдержанных форматов.
- Track Prep JSON-разметка в `F:\AutoSet\set_app\track_marks`.
- Диагностика Engine cue/loop blobs и codec round-trip.
- Экспорт выбранной Track Prep-разметки в Engine DJ с backup и проверкой конфликтов.
- Auto Suggest Marks для одного трека и Batch Suggest Preview.
- Серия layout/UI-правок до версии `1.5.24`.

## Что изменилось после аудита 2026-06-17

- Версия выросла с `1.5.12` до `1.5.24`.
- Добавлен ручной Track Prep: marks `MIX_IN`, `VOCAL_IN`, `DROP`, `BREAK`, `MIX_OUT`, `OUTRO` и loops `OUTRO_LOOP`, `EMERGENCY_LOOP`.
- Track Prep хранится в JSON, а не сразу в Engine DB.
- Добавлены endpoints `GET/POST/DELETE /api/track_marks`.
- Добавлены dev-tools `tools/engine_db_diff_cues.py` и `tools/engine_cue_loop_codec.py`.
- Добавлен безопасный экспорт выбранного трека в Engine DJ `PerformanceData.quickCues/loops`.
- Добавлены backups Engine DB в `F:\AutoSet\set_app\backups\engine_db`.
- Добавлены улучшения waveform UX: seek до Play, zoom navigation, hover time, snap preview, selected mark, loop-from-mark.
- Добавлен `POST /api/suggest_track_marks`.
- Добавлен Batch Suggest Preview для выбранных/видимых треков.
- Существенно переработан layout: compact controls, 4-block layout, верхняя строка Play/Overview/Volume, восстановление нижних панелей после регрессий.
- Добавлены и исправлялись версии `1.5.13` ... `1.5.24` в CHANGELOG.
- В отчетах появилось больше прогонов `engine_write_tags_*`, включая каталоги от `2026-06-28` и `2026-06-29`.
- Физически появились 4 JSON-файла Track Prep-разметки.
- В рабочем дереве появился незакоммиченный слой по MIME/media-check/WebAudio playback.

## Готовые результаты

- `F:\Music\Sets`: 12 папок сетов, включая house/techno-сеты с `playlist.csv`, `playlist.m3u` и местами `methodology.txt`.
- `F:\AutoSet\reports`: 50 элементов, включая множество каталогов `engine_write_tags_YYYYMMDD_HHMMSS` и `genres`.
- `F:\AutoSet\set_app\track_marks`: 4 JSON-файла разметки.
- `F:\AutoSet\set_app\backups\engine_db`: 4 backup-копии `m.db`.
- `F:\Engine Library\Database2\m.db`: 295747584 байт, 10 таблиц, 11876 строк в `Track` и 11876 строк в `PerformanceData`.
- `F:\Music`: 12003 аудиофайла по расширениям: 11834 MP3, 136 FLAC, 22 M4A, 10 OGG, 1 WAV.

## Открытые вопросы

- Нужно ли коммитить текущий незакоммиченный слой WebAudio/media playback или он временный/экспериментальный - не найдено в доступных материалах.
- Почему предыдущий аудит от `2026-06-17` лежит в `F:\AutoSet\install`, а не в `F:\Music` - не найдено в доступных материалах.
- Нужно ли хранить `install/AutoSet_*_2026-06-17.*` в Git или оставить как локальные audit-артефакты - не найдено в доступных материалах.
- Что такое `set_app/index1.html` и `set_app/set_app1.py` - не найдено в доступных материалах.
- Нужно ли восстановить/пересоздать `codex_dj_meta.sqlite`: по старым чатам он создавался в ранней схеме, но сейчас `F:\Music\Engine Library\codex_dj_meta.sqlite` не найден.

## Следующие шаги

1. Разобрать и зафиксировать состояние незакоммиченных изменений `F:\AutoSet`.
2. Протестировать текущий UI версии `1.5.24` с учетом незакоммиченного WebAudio/media слоя.
3. Проверить Track Prep: manual marks, suggest, batch suggest, save/load JSON, export to Engine DJ, backup/conflict/overwrite.
4. Обновить README/CHANGELOG под фактическое состояние `1.5.24` и незакоммиченные изменения, если они будут приняты.
5. Навести порядок с audit-файлами: новый комплект хранить в `F:\Music`; старый комплект не удалять.
