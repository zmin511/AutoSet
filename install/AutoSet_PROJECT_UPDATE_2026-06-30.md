# AutoSet: актуальное описание проекта на 2026-06-30

## Название проекта

`AutoSet`

## Назначение

`AutoSet` - локальное portable-приложение для Denon Engine DJ. Оно читает Engine DJ SQLite DB, показывает музыкальную библиотеку и waveform, помогает строить гармоничные DJ-сеты, управляет жанрами/тегами, создает Engine-плейлисты и теперь поддерживает Track Prep-разметку cue/loop с JSON-хранением, auto/batch suggestions и безопасным экспортом выбранного трека в Engine DJ.

## Текущий статус

- Аудит: `2026-06-30`.
- Актуальная версия по коду и README: `1.5.24`.
- Код: `F:\AutoSet`.
- Медиатека и workspace: `F:\Music`.
- Engine DB: `F:\Engine Library\Database2\m.db`.
- GitHub: `https://github.com/zmin511/AutoSet.git`.
- Последний коммит: `5c144a2 Fix missing library frame in lower layout`.
- Рабочее дерево `F:\AutoSet` сейчас не чистое; особенно важен незакоммиченный слой в `set_app/index.html` по audio/WebAudio/media playback.

## Что уже сделано

- Engine DB используется как основной источник Track/PerformanceData/Playlist.
- Сеты создаются в `F:\Music\Sets`; сейчас там 12 сет-папок.
- В медиатеке `F:\Music` найдено 12003 аудиофайла.
- Поддерживаются waveform overview/zoom, Follow, cue/loop labels.
- Поддерживаются запись тегов в Engine DB и MP3/FLAC/M4A через `mutagen`.
- Добавлен Track Prep:
  - ручные marks/loops;
  - JSON в `F:\AutoSet\set_app\track_marks`;
  - 4 существующих JSON-разметки;
  - auto suggest для одного трека;
  - batch suggest preview;
  - export selected marks/loops to Engine DJ с backup и conflict/overwrite.
- Добавлены diagnostics/codec tools для Engine `quickCues` и `loops`.
- Добавлены backups Engine DB: 4 файла в `F:\AutoSet\set_app\backups\engine_db`.

## Что сейчас важно

1. Не начинать новые крупные правки, пока не разобран текущий dirty git status в `F:\AutoSet`.
2. Не считать незакоммиченный WebAudio/media playback слой готовым релизом без браузерной проверки.
3. Не удалять старые audit-файлы и untracked/debug-файлы без явного разрешения.
4. Track Prep export и tag write делать только с backup/dry-run и понятным отчетом.
5. Старый проект `F:\zmin_autoset` не считать актуальным кодом.

## Ближайшие следующие шаги

1. Провести review текущего diff в `F:\AutoSet`.
2. Протестировать UI `1.5.24` с незакоммиченными audio/WebAudio изменениями.
3. Решить, коммитить ли `.gitignore`, `run_windows.cmd`, `set_app.py`, `index.html`.
4. Проверить Track Prep end-to-end.
5. После стабилизации обновить README/CHANGELOG и, при необходимости, GitHub.

## Актуальные Markdown-файлы этого аудита

- `AutoSet_PROJECT_SUMMARY_2026-06-30.md`
- `AutoSet_TECHNICAL_DETAILS_2026-06-30.md`
- `AutoSet_CHAT_HISTORY_DIGEST_2026-06-30.md`
- `AutoSet_TODO_AND_NEXT_STEPS_2026-06-30.md`
- `AutoSet_PROJECT_UPDATE_2026-06-30.md`

## Текст для обновления описания проекта

```text
AutoSet — локальное portable-приложение для Denon Engine DJ. Статус на 2026-06-30: версия 1.5.24, основной код в F:\AutoSet, медиатека/workspace в F:\Music, Engine DB в F:\Engine Library\Database2\m.db, GitHub remote https://github.com/zmin511/AutoSet.git.

Проект читает Engine DJ DB, показывает библиотеку и waveform, строит DJ-сеты, создает Engine-плейлисты, управляет жанрами/тегами и поддерживает Track Prep: ручные marks/loops, JSON-хранение в F:\AutoSet\set_app\track_marks, auto/batch suggestions и безопасный экспорт выбранного трека в Engine DJ с backup/conflict/overwrite.

Актуальная документация аудита лежит в F:\Music:
AutoSet_PROJECT_SUMMARY_2026-06-30.md,
AutoSet_TECHNICAL_DETAILS_2026-06-30.md,
AutoSet_CHAT_HISTORY_DIGEST_2026-06-30.md,
AutoSet_TODO_AND_NEXT_STEPS_2026-06-30.md,
AutoSet_PROJECT_UPDATE_2026-06-30.md.

Следующему чату учитывать: F:\AutoSet сейчас имеет незакоммиченные изменения (.gitignore, set_app/index.html, set_app/run_windows.cmd, set_app/set_app.py и untracked debug/install/index1/set_app1). Сначала проверить git status/diff. Не использовать F:\zmin_autoset как актуальный код. Массовые tag write и Engine DB export делать только после dry-run/backup.
```
