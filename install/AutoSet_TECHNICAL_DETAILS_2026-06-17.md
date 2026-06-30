# AutoSet: технические детали на 2026-06-17

## Архитектура

`AutoSet` - локальное приложение без отдельного backend-фреймворка. Основная схема:

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
  tools\
    engine_config.py
    engine_set_builder.py
    engine_write_tags.py
    review_new_genres.py
  reports\
  tag_backups\
```

`set_app.py` запускает `ThreadingHTTPServer` на `127.0.0.1`, обычно порт `8765`, и открывает UI в браузере. UI находится в одном HTML-файле `index.html` с CSS/JS.

## Источники данных

### Основная база

Основной источник данных - SQLite-база Denon Engine DJ:

```text
F:\Engine Library\Database2\m.db
```

Read-only проверка на дату аудита:

- таблиц: 10;
- `Track`: 11876 строк;
- `PerformanceData`: 11876 строк;
- `Playlist`: 1542 строки;
- `PlaylistEntity`: 46890 строк;
- `Information`: 1 строка.

Ключевые таблицы:

- `Track`:
  - `id`;
  - `path`, `filename`, `fileBytes`;
  - `length`;
  - `bitrate`;
  - `bpm`, `bpmAnalyzed`;
  - `key`;
  - `genre`;
  - `artist`, `title`, `album`;
  - `rating`;
  - `lastEditTime`;
  - `isAvailable`, `isAnalyzed`.
- `PerformanceData`:
  - `trackId`;
  - `overviewWaveFormData`;
  - `beatData`;
  - `quickCues`;
  - `loops`.
- `Playlist`:
  - `id`, `title`, `parentListId`, `nextListId`, `lastEditTime`.
- `PlaylistEntity`:
  - `id`, `listId`, `trackId`, `databaseUuid`, `nextEntityId`, `membershipReference`.
- `Information`:
  - `uuid`, schema version fields.

### Музыкальная библиотека

Основная папка медиатеки:

```text
F:\Music
```

На дату аудита найдено 11998 аудиофайлов. Основные верхние папки включают `Club`, `Dance`, `DnB`, `Genre`, `New`, `Rock`, `Rus`, `Set`, `Sets`, `Slow`.

### Результаты AutoSet

Основной output:

```text
F:\Music\Sets
```

Найдено 12 папок сетов. Внутри есть скопированные треки, `playlist.m3u`, `playlist.csv`, иногда `methodology.txt`.

Отчеты:

```text
F:\AutoSet\reports
```

Найдено 12 CSV-файлов отчетов, включая:

- `engine_write_tags_YYYYMMDD_HHMMSS\report.csv`;
- `genres\new_genre_review_New_YYYYMMDD_HHMMSS.csv`.

## Конфигурация путей

`tools\engine_config.py` и `set_app\set_app.py` используют схему:

- `REPO_DIR = F:\AutoSet`;
- `DISK_ROOT = F:\`;
- `music_root` по умолчанию `F:\Music`;
- `db_path` по умолчанию `F:\Engine Library\Database2\m.db`;
- `report_dir` по умолчанию `F:\AutoSet\reports`;
- `backup_dir` по умолчанию `F:\AutoSet\tag_backups`;
- `out_dir` по умолчанию `F:\Music\Sets`.

Пользовательская конфигурация может храниться в:

```text
F:\AutoSet\set_app\paths.json
```

Если файл отсутствует, применяются fallback-пути.

## Основные API и функции backend

В `set_app.py` реализованы GET/POST endpoints через `BaseHTTPRequestHandler`.

Подтвержденные endpoints из кода и чатов:

- `GET /` - отдает `index.html`;
- `GET /api/config` - конфигурация/статус;
- `GET /api/genres` - список жанров;
- `GET /api/performance` - старый endpoint performance/waveform;
- `GET /api/db-diagnostics` - read-only диагностика Engine DB;
- `GET /api/track_waveform_detail?track_id=...` - подробная структура waveform/cue/loop/beat-grid;
- `POST /api/build` - построение локального сета;
- `POST /api/engine-playlist` - создание Engine-плейлиста;
- `POST /api/refresh-tags` - обновление тегов для папки;
- `POST /api/write-energy-ratings` - запись energy/rating для текущей папки;
- `POST /api/write-all-energy-ratings` - запись energy/rating для всей медиатеки;
- `POST /api/update-genre` - одиночное изменение жанра;
- `POST /api/bulk-genre` - массовое добавление/замена/удаление жанров;
- `POST /api/detail-styles` - поиск/применение детальных стилей;
- `POST /api/config` - сохранение путей.

## Алгоритм подбора сета

Основной файл:

```text
F:\AutoSet\tools\engine_set_builder.py
```

Ключевые элементы:

- dataclass `Track` хранит `id`, `filename`, `length`, `bitrate`, `bpm`, `key`, `genre`, `artist`, `title`, `path`, `wave_energy`, `dj_style`, `dj_family`, `dj_set_ok`.
- `engine_key_to_camelot()` переводит Engine key в Camelot.
- `camelot_score()` и `camelot_relation()` считают расстояние по Camelot; A/B не увеличивает числовое расстояние.
- `genre_family()`, `style_buckets()`, `candidate_style_values()` нормализуют стиль/семейство.
- `track_has_rus_tag()` и `SPECIAL_ALLOW_STYLES = {"rus"}` поддерживают `Rus` как допуск.
- `energy_score()` оценивает энергию.
- `transition_score()` учитывает BPM delta, Camelot relation, genre distance, energy delta.
- `build_start_set()` строит сет от стартового трека с ростом энергии.
- `build_peak_set()` строит сет вокруг peak-трека с последующим снижением.
- `write_outputs()` создает `playlist.m3u`, `playlist.csv`, `methodology.txt` и копирует треки, если не выбран no-copy режим.
- CLI поддерживает `--emit-playlist-json` для backend.

Важное решение: Engine-плейлист создается по `Track.id`, а не только по `Track.path`. Это исправило проблему русских путей/кодировок, когда путь мог не совпасть строка-в-строку.

## Waveform, cue, loop и beat-grid

Backend читает:

- `PerformanceData.overviewWaveFormData` - RGB overview waveform;
- `PerformanceData.quickCues` - Cue 1..8;
- `PerformanceData.loops` - Loop 1..8;
- `PerformanceData.beatData` - используется, если данных достаточно.

Если `beatData` дает слишком мало точек, строится fallback-сетка по BPM:

```text
beat_interval = 60 / bpm
```

UI показывает:

- overview waveform;
- zoom waveform;
- beat-grid;
- каждый 4-й beat заметнее;
- каждый 16-й beat еще заметнее;
- cue/loop markers;
- playhead;
- zoom controls;
- follow mode.

В changelog/чатах зафиксировано:

- `c85e0e9 Add detailed waveform view`;
- `30d9a6c Improve waveform layout and follow playhead behavior`;
- `3557540 Tune waveform zoom defaults and compact view`;
- `eb5d106 Fix waveform follow overview seek behavior`.

## Работа с жанрами и стилями

### Локальные жанры

`set_app.py` содержит:

- `split_genre_tags()`;
- `join_genre_tags()`;
- `_normalize_genre_value()`;
- `update_genre()`;
- `bulk_update_genres()`;
- `_genre_after_bulk_action()`.

Массовые действия:

- добавить тег к текущей папке;
- заменить тег;
- удалить тег;
- работать только по текущей папке или с подпапками.

### Онлайн-стили

Решение из чатов: локальная папка не должна быть источником правды для жанра, потому что папка может называться как угодно и содержать разные стили.

Используются:

- Discogs - основной полезный источник для электронной музыки, потому что есть `style`;
- MusicBrainz - открытая база, но по чатам слабее для точных электронных подстилей;
- Last.fm - опционально через `LASTFM_API_KEY` или `set_app\lastfm_api_key.txt`.

MetaBrainz Picard рассматривался как архитектурный ориентир. Код напрямую не копировался из-за лицензии GPL.

Онлайн-preview ограничивался, чтобы UI не зависал на длинной папке. В чатах фигурировал лимит первых 10 треков для MusicBrainz/Discogs preview.

## Запись тегов в аудиофайлы

Файл:

```text
F:\AutoSet\tools\engine_write_tags.py
```

Зависимость:

```text
mutagen>=1.47,<2
```

Главная функция:

```text
write_audio_tags(file_path, genre=None, bpm=None, key=None, autoset_styles=None, rating=None, dry_run=False)
```

Форматы:

- MP3:
  - `TCON` genre;
  - `TBPM` BPM;
  - `TKEY` key;
  - `TXXX:AutoSet Styles`;
  - `COMM:AutoSet`;
  - `POPM` rating best-effort.
- FLAC:
  - `GENRE`;
  - `BPM`;
  - `INITIALKEY` и `KEY`;
  - `AUTOSET_STYLES`;
  - `RATING`.
- M4A/MP4:
  - `©gen`;
  - `tmpo`;
  - custom atoms for key/styles;
  - rating не пишется надежно, возвращается warning.
- WAV/AIFF:
  - запись не выполняется;
  - warning: `File tag writing is not supported for this format yet`.

Перед записью проверяется:

- файл существует;
- путь является файлом;
- файл не read-only;
- файл не locked.

Типичный JSON результата:

```json
{
  "ok": true,
  "file_tags_updated": true,
  "file_tags_warning": null,
  "written_fields": ["genre", "bpm", "key", "autoset_styles", "rating"],
  "skipped_fields": [],
  "path": "..."
}
```

В UI предупреждение о частичном успехе означает: Engine DB обновлена, но файл не был обновлен, поэтому после пересканирования Engine изменение может пропасть.

## Ограничения и риски

- Массовые операции тегов изменяют библиотеку; перед широким применением нужен малый тестовый набор.
- `tag_backups` существует, но на момент аудита файлов backup не найдено.
- WAV/AIFF не поддерживаются для записи тегов.
- M4A/MP4 rating не пишется надежно.
- Внешние API могут быть медленными, неполными или ограниченными:
  - MusicBrainz медленный и не всегда дает конкретный стиль;
  - Discogs лучше по `style`, но качество зависит от найденного релиза;
  - Last.fm требует ключ для полноценной работы.
- Русские README/CHANGELOG в консоли местами отображались как mojibake; сами файлы и браузерный UI могут читать их корректно, но кодировку стоит проверить отдельно.
- В доступных материалах не найден полноценный автоматизированный тестовый набор.

## Что нужно знать следующему ассистенту

- Не искать актуальный проект в `F:\zmin_autoset`: эта папка больше не существует. Текущий проект - `F:\AutoSet`.
- `F:\zmin_autoset_versions` нужен только для истории и архивов.
- Рабочая медиатека - `F:\Music`; результаты AutoSet - `F:\Music\Sets`.
- Engine DB - `F:\Engine Library\Database2\m.db`.
- Любые write-операции по аудиотегам выполнять осторожно, сначала на копии или малой папке.
- Создание Engine-плейлистов должно опираться на `Track.id`, а не на повторный поиск по path.
- `Rus` - это допуск, а не обычный музыкальный стиль.
- Picard использовать только как идею workflow, не копировать код без лицензионного анализа.
- Перед изменениями проверять `git status` в `F:\AutoSet`.
