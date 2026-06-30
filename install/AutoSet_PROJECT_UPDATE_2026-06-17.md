# AutoSet: актуальный снимок проекта на 2026-06-17

## Название проекта

`AutoSet`

## Назначение

Локальное portable-приложение для Denon Engine DJ. Помогает читать Engine DB, просматривать треки с waveform/cue/loop, подбирать гармоничные DJ-сеты по BPM/Camelot/жанрам/энергии, создавать локальные сет-папки и Engine-плейлисты, а также редактировать жанры/теги с записью в Engine DB и поддержанные аудиофайлы.

## Текущий статус

- Актуальная версия: `1.5.12`.
- Код: `F:\AutoSet`.
- Медиатека: `F:\Music`.
- Engine DB: `F:\Engine Library\Database2\m.db`.
- GitHub: `https://github.com/zmin511/AutoSet.git`.
- Предыдущие Markdown-аудиты не найдены; этот аудит является базовым.

## Что уже сделано

- Проект переименован из `zmin_autoset` в `AutoSet`.
- Настроен локальный Python server + браузерный UI.
- Реализовано чтение Engine DB `Track`, `PerformanceData`, `Playlist`, `PlaylistEntity`.
- Реализованы set builder и Engine playlist writer.
- Добавлены waveform overview/zoom, beat-grid, cue/loop markers, playhead и Follow mode.
- Добавлены energy stars и запись рейтинга в Engine DB.
- Добавлен менеджер жанров текущей папки.
- Добавлен допуск `Rus`.
- Добавлен online style lookup через Discogs, MusicBrainz, опционально Last.fm.
- Добавлена запись тегов в MP3/FLAC/M4A через `mutagen`; WAV/AIFF возвращают безопасный warning.
- Последние изменения опубликованы в GitHub `main`.

## Что сейчас важно

- Не путать актуальный проект `F:\AutoSet` со старой историей `F:\zmin_autoset_versions`.
- Любые массовые операции тегов проверять сначала на копиях.
- При создании Engine-плейлистов использовать `Track.id`, не полагаться только на путь.
- `Rus` - это отдельный допуск при подборе, а не обычный стиль.
- Picard рассматривался только как ориентир; код Picard напрямую не копировать без лицензионного анализа.

## Ближайшие следующие шаги

1. Сделать контролируемый тест массовой записи тегов на копиях MP3/FLAC/M4A.
2. Добавить автотесты для `tools\engine_write_tags.py`.
3. Проверить и при необходимости включить backup перед массовыми tag write.
4. Документировать backend endpoints.
5. Проверить кодировку русских README/CHANGELOG.

## Актуальные Markdown-файлы аудита

- `AutoSet_PROJECT_SUMMARY_2026-06-17.md`
- `AutoSet_TECHNICAL_DETAILS_2026-06-17.md`
- `AutoSet_CHAT_HISTORY_DIGEST_2026-06-17.md`
- `AutoSet_TODO_AND_NEXT_STEPS_2026-06-17.md`
- `AutoSet_PROJECT_UPDATE_2026-06-17.md`
