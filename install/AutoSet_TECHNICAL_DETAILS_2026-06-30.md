# AutoSet: технические детали на 2026-06-30

## Архитектура

`AutoSet` состоит из локального Python backend и браузерного UI.

```text
F:\AutoSet\
  run_windows.cmd
  run_mac.command
  requirements.txt
  README.md / README_RU.md / README_EN.md / CHANGELOG.md
  set_app\
    set_app.py
    index.html
    run_windows.cmd
    run_mac.command
    track_marks\
    backups\engine_db\
  tools\
    engine_config.py
    engine_set_builder.py
    engine_write_tags.py
    review_new_genres.py
    engine_db_diff_cues.py
    engine_cue_loop_codec.py
  reports\
  tag_backups\
```

Backend находится в `F:\AutoSet\set_app\set_app.py`. UI находится в `F:\AutoSet\set_app\index.html`. Проект использует локальный HTTP-сервер, обычно на `127.0.0.1:8765`, с переходом на свободный порт в более ранней логике, если порт занят.

## Версия и Git

- `APP_VERSION = "1.5.24"`.
- `README.md` и `CHANGELOG.md` также указывают `1.5.24`.
- Remote: `origin https://github.com/zmin511/AutoSet.git`.
- Последний локальный коммит: `5c144a2 Fix missing library frame in lower layout`.
- Ветка с незакоммиченными изменениями:
  - `.gitignore`: добавлено `set_app/track_marks/`.
  - `set_app/run_windows.cmd`: усилен выбор Python и установка `requirements.txt` при отсутствии `mutagen`.
  - `set_app/set_app.py`: добавлены `AUDIO_MIME_TYPES` и `/api/media-check`, MIME для `/media`.
  - `set_app/index.html`: большой незакоммиченный слой для audio preload, playback cursor pinning, WebAudio fallback, media blob URL, аудио diagnostics и seek/playback logic.
  - untracked: `debug/`, предыдущие audit-файлы в `install/`, `set_app/index1.html`, `set_app/set_app1.py`.

## Основные источники данных

### Engine DJ DB

Основная база:

```text
F:\Engine Library\Database2\m.db
```

Read-only проверка на дату аудита:

- размер: `295747584` байт;
- таблиц: `10`;
- `Track`: `11876`;
- `PerformanceData`: `11876`;
- `Playlist`: `1542`;
- `PlaylistEntity`: `43728`;
- `AlbumArt`: `5376`;
- `Information`: `1`;
- `Pack`, `PreparelistEntity`, `Smartlist`: `0`.

Ключевые таблицы:

- `Track`: метаданные трека, путь, artist/title, genre, BPM, key, length, bitrate, rating, `lastEditTime`.
- `PerformanceData`: waveform, beat data, quick cues, loops.
- `Playlist` и `PlaylistEntity`: структура Engine-плейлистов.

### Музыкальная библиотека

Основной корень:

```text
F:\Music
```

На дату аудита найдено `12003` аудиофайла:

- `.mp3`: `11834`;
- `.flac`: `136`;
- `.m4a`: `22`;
- `.ogg`: `10`;
- `.wav`: `1`.

Крупные разделы по количеству аудиофайлов:

- `Rus`: `3504`;
- `Dance`: `3126`;
- `Genre`: `2775`;
- `Club`: `1244`;
- `Old dance`: `363`;
- `Rock`: `250`;
- `DnB`: `179`;
- `New`: `163`;
- `Sets`: `151`;
- `Set`: `129`.

### Output сетов

```text
F:\Music\Sets
```

Сейчас содержит `12` папок сетов. Внутри лежат скопированные аудиофайлы, `playlist.m3u`, `playlist.csv`, местами `methodology.txt`.

### Track Prep JSON

```text
F:\AutoSet\set_app\track_marks
```

Сейчас содержит `4` JSON-файла:

- `track_1_e29c5b316d62bfc9.json`;
- `track_9_8081681252d95ea0.json`;
- `track_10_e880e36b6c820813.json`;
- `track_11796_e9f28d8df43c6861.json`.

JSON содержит `track_id`, `file_path`, `file_size`, `duration_sec`, `bpm`, `marks[]`, `loops[]`, `source`, `confidence`, snap-поля и raw time-поля.

### Backups Engine DB

```text
F:\AutoSet\set_app\backups\engine_db
```

Найдено `4` backup-файла:

- `20260621_074638_m.db`;
- `20260621_075936_m.db`;
- `20260628_084418_m.db`;
- `20260628_084429_m.db`.

## Backend API и важные endpoints

Подтверждено по коду, README/CHANGELOG и чатам:

- `GET /` - UI.
- `GET /api/config` - конфигурация, версия, пути.
- `GET /api/disk-tree` - дерево диска для выбора путей.
- `GET /api/track_waveform_detail?track_id=...` - waveform detail, duration, BPM, beat grid, energy.
- `GET /api/track_marks?track_id=...` - чтение Track Prep JSON.
- `POST /api/track_marks` - сохранение Track Prep JSON.
- `DELETE /api/track_marks?track_id=...` - удаление Track Prep JSON.
- `POST /api/export_track_marks` - экспорт сохраненной разметки выбранного трека в Engine DJ.
- `POST /api/suggest_track_marks` - auto-suggest для одного трека.
- `POST /api/batch_suggest_track_marks` - batch suggest preview.
- `GET /media?path=...` - отдача аудиофайла.
- `GET /api/media-check?path=...` - найдено в незакоммиченном diff, проверяет путь, размер и MIME.

## Track Prep решения

- Разметка сначала хранится во внутренних JSON, без немедленной записи в Engine DB.
- Auto-suggest не сохраняется автоматически и не экспортируется в Engine DJ до принятия.
- Batch Suggest Preview также read-only до явного Accept.
- Экспорт в Engine DJ ограничен выбранным треком, делает backup `m.db`, проверяет конфликты слотов и требует overwrite mode для замены.
- Codec для Engine cue/loop вынесен в `tools/engine_cue_loop_codec.py`.
- Диагностика before/after DB вынесена в `tools/engine_db_diff_cues.py`.
- По чатам raw position для cue/loop считался связанным с frames at 44100 Hz; формула сначала была отмечена как требующая подтверждения, затем использовалась в экспортной логике. Детальную валидацию по новым контрольным меткам перед массовым применением стоит повторить.

## Теги и интеграции

- `requirements.txt`: `mutagen>=1.47,<2`.
- `tools/engine_write_tags.py` пишет supported tags в MP3/FLAC/M4A.
- WAV/AIFF не пишутся рискованно, возвращается warning.
- UI показывает частичный успех, если Engine DB обновлена, а файл не обновлен.
- Launcher `set_app/run_windows.cmd` в незакоммиченном diff проверяет `mutagen` и ставит зависимости из `requirements.txt`, если их нет.
- Использовались или проектно предусмотрены Discogs, MusicBrainz, Last.fm для style lookup; iTunes/MusicBrainz также встречались в старой ветке внешнего жанрового enrichment.

## Set builder

`tools\engine_set_builder.py` строит сет на основе:

- выбранного anchor track;
- роли anchor: start/peak;
- BPM-коридора;
- Camelot-совместимости;
- жанровой/стилевой близости;
- примерной энергии;
- ограничений на дубли и слишком похожие версии;
- длительности около часа или заданного режима.

Результат:

- папка с копиями треков;
- `playlist.m3u`;
- `playlist.csv`;
- `methodology.txt`, если используется текущая логика.

## Ограничения и риски

- Текущий `F:\AutoSet` не является чистым git-состоянием. Нельзя считать незакоммиченные изменения проверенным релизом.
- В `F:\Music` лежат root-level helper-скрипты `autoset_step_*.py` и `autoset_patch_*.py`, которые патчат `F:\AutoSet`. Они являются рабочими артефактами, а не частью основного репозитория.
- В консоли часть русских README/CHANGELOG отображается mojibake, но это похоже на проблему кодировки вывода, а не обязательно на повреждение файлов.
- `codex_dj_meta.sqlite`, упоминавшийся в старых чатах, сейчас по пути `F:\Music\Engine Library\codex_dj_meta.sqlite` не найден.
- Старые audit-файлы от `2026-06-17` лежат в `F:\AutoSet\install` как untracked; решение о хранении в Git не найдено.

## Что нужно знать следующему ассистенту

1. Не работать со старой папкой `F:\zmin_autoset` как с актуальной: актуальный код находится в `F:\AutoSet`.
2. `F:\Music` - это медиатека и workspace; новый аудит от `2026-06-30` создан именно в `F:\Music`.
3. Перед любыми изменениями проверить `git -C F:\AutoSet status --porcelain=v1`.
4. Не удалять untracked или helper-файлы без явного разрешения пользователя.
5. Массовые операции с аудиотегами делать только после dry-run и понятного отчета.
6. Export Track Prep в Engine DB делать только с backup и проверкой conflict/overwrite.
7. Если продолжать audio playback/WebAudio diff, сначала протестировать UI в браузере и JS console.
