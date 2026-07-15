# AutoSet

Version: `1.5.45` | Changelog: `CHANGELOG.md` | Audit: `2026-06-30`

**AutoSet** is a local portable companion app for **Denon Engine DJ**. It reads the Engine DJ SQLite database, helps build harmonic DJ sets by BPM, Camelot key, style, duration, and energy, visualizes waveform/cue/loop data, creates Engine playlists, and manages DJ genre/tag metadata with optional online style lookup.

## Русское описание

`AutoSet` - локальное portable-приложение для **Denon Engine DJ**. Оно помогает читать Engine DB, просматривать треки с waveform/cue/loop, подбирать гармоничные DJ-сеты от выбранного опорного трека, создавать локальные сет-папки и Engine-плейлисты, а также редактировать жанры и теги с записью в Engine DB и поддержанные аудиофайлы.

Базовый сценарий работает локально. Для уточнения стилей можно опционально использовать онлайн-lookup через Discogs, MusicBrainz и Last.fm.

### Текущий статус

- Актуальная версия: `1.5.45`.
- Основной код: `set_app/` и `tools/`.
- Основной источник данных: `Engine Library/Database2/m.db`.
- Последний аудит проекта: `2026-06-17`.
- Предыдущие Markdown-аудиты в доступных материалах не найдены; аудит от `2026-06-17` считается базовой версией.

### Что умеет

- Выбирать опорный трек из библиотеки Engine или папок `Music/`.
- Подбирать сет по BPM, Camelot, жанру/стилю, длительности, битрейту и примерной энергии.
- Работать с двумя ролями опорного трека: `Начало` и `Кульминация`.
- Прослушивать треки во встроенном плеере.
- Показывать Engine-like waveform, детальную waveform, zoom, beat-grid, cue, loop, playhead и Follow mode.
- Создавать папку с копиями треков, `playlist.m3u`, `playlist.csv` и `methodology.txt`.
- Создавать плейлист прямо в Engine DB ссылками на существующие `Track.id`.
- Добавлять, заменять и удалять жанровые теги для текущей папки или папки с подпапками.
- Использовать `Rus` как отдельный opt-in допуск при подборе, а не как обычный стиль.
- Искать стили онлайн через Discogs, MusicBrainz и опционально Last.fm.
- Записывать energy stars в `Track.rating` Engine DB.
- Записывать поддержанные теги в MP3, FLAC и M4A через `mutagen`; WAV/AIFF получают безопасное предупреждение без записи.

### Как работает

Главный источник данных - SQLite-база Engine:

```text
Engine Library/Database2/m.db
```

Приложение читает:

- `Track` - путь к файлу, artist/title/genre, BPM, key, length, bitrate, rating и служебные поля;
- `PerformanceData.overviewWaveFormData` - цветную overview-waveform;
- `PerformanceData.trackData` и связанные данные для более детального waveform-представления;
- `PerformanceData.quickCues` - Cue 1..8;
- `PerformanceData.loops` - Loop 1..8;
- `Playlist` и `PlaylistEntity` - структуру плейлистов Engine.

Алгоритм подбора оценивает соседние переходы: разницу BPM, расстояние по Camelot, близость жанров/стилей, энергию waveform, длину, битрейт и похожие версии одного трека. A/B не увеличивает Camelot-расстояние.

### Запуск

Рекомендуемая структура:

```text
<корень диска>/
  AutoSet/
  Music/
  Engine Library/
    Database2/
      m.db
```

Запуск:

- Windows: `AutoSet\run_windows.cmd`
- macOS: `AutoSet/run_mac.command`

Интерфейс обычно открывается здесь:

```text
http://127.0.0.1:8765/
```

Не открывайте `set_app/index.html` напрямую: для работы нужен локальный Python-сервер.

### Основные файлы

```text
set_app/set_app.py          локальный сервер, API, конфигурация, Engine DB, waveform, playlists, style lookup
set_app/index.html          браузерный интерфейс
tools/engine_set_builder.py алгоритм построения сета
tools/engine_config.py      общая конфигурация путей
tools/engine_write_tags.py  запись тегов в MP3/FLAC/M4A через mutagen
tools/review_new_genres.py  нормализация жанров, семейств и DJ-тегов
```

Полная русская документация: `README_RU.md`

### Что важно дальше

- Проверить массовую запись тегов на копиях MP3/FLAC/M4A.
- Добавить автотесты для `tools/engine_write_tags.py`.
- Проверить и при необходимости включить backup перед массовыми tag write операциями.
- Документировать backend endpoints.
- Проверить кодировку русских README/CHANGELOG при локальном просмотре в Windows-консоли.

---

## English Description

`AutoSet` is a local portable companion app for **Denon Engine DJ**. It reads the Engine DJ database, previews tracks with waveform/cue/loop data, builds harmonic DJ sets from a selected reference track, creates local set folders and Engine playlists, and manages genre/tag metadata with writes back to Engine DB and supported audio files.

The core workflow is local. Optional online style lookup can use Discogs, MusicBrainz, and Last.fm.

### Current Status

- Current version: `1.5.45`.
- Main code: `set_app/` and `tools/`.
- Main data source: `Engine Library/Database2/m.db`.
- Latest project audit: `2026-06-17`.
- No earlier Markdown audits were found in the available materials; the `2026-06-17` audit is the baseline audit.

### Features

- Pick a reference track from the Engine library or `Music/` folders.
- Build a set by BPM, Camelot key, genre/style, duration, bitrate, and estimated energy.
- Use the reference track as `Start` or `Peak`.
- Preview tracks in the built-in player.
- Render Engine-like waveform, detailed waveform, zoom, beat-grid, cues, loops, playhead, and Follow mode.
- Create a copied set folder with `playlist.m3u`, `playlist.csv`, and `methodology.txt`.
- Create an Engine DB playlist linked to existing `Track.id` records.
- Add, replace, and remove genre tags for the current folder or folder plus subfolders.
- Treat `Rus` as a separate opt-in allowance during set building, not as a normal style.
- Look up styles online via Discogs, MusicBrainz, and optionally Last.fm.
- Write estimated energy stars to Engine DJ `Track.rating`.
- Write supported tags to MP3, FLAC, and M4A via `mutagen`; WAV/AIFF return a safe warning without writing.

### How It Works

The main data source is the Engine SQLite database:

```text
Engine Library/Database2/m.db
```

The app reads:

- `Track` - file path, artist/title/genre, BPM, key, length, bitrate, rating, and supporting metadata;
- `PerformanceData.overviewWaveFormData` - RGB overview waveform;
- `PerformanceData.trackData` and related data for a more detailed waveform view;
- `PerformanceData.quickCues` - Cue 1..8;
- `PerformanceData.loops` - Loop 1..8;
- `Playlist` and `PlaylistEntity` - Engine playlist structure.

The builder scores adjacent transitions by BPM delta, Camelot distance, genre/style proximity, waveform energy, track length, bitrate, and near-duplicate versions of the same song. A/B does not increase Camelot distance.

### Run

Recommended layout:

```text
<drive root>/
  AutoSet/
  Music/
  Engine Library/
    Database2/
      m.db
```

Run:

- Windows: `AutoSet\run_windows.cmd`
- macOS: `AutoSet/run_mac.command`

The UI usually opens at:

```text
http://127.0.0.1:8765/
```

Do not open `set_app/index.html` directly; the local Python server is required.

### Main Files

```text
set_app/set_app.py          local server, API, config, Engine DB, waveform, playlists, style lookup
set_app/index.html          browser interface
tools/engine_set_builder.py set-building algorithm
tools/engine_config.py      shared path configuration
tools/engine_write_tags.py  writes tags to MP3/FLAC/M4A through mutagen
tools/review_new_genres.py  normalizes genres, families, and DJ tags
```

Full English documentation: `README_EN.md`

### Next Priorities

- Run controlled bulk tag-write tests on MP3/FLAC/M4A copies.
- Add automated tests for `tools/engine_write_tags.py`.
- Verify and, if needed, enable backups before bulk tag-write operations.
- Document backend endpoints.
- Check Russian README/CHANGELOG encoding when viewed locally in Windows console.



## Track Analysis и подбор переходов

AutoSet 1.5.45 добавляет отдельную локальную базу `data/analysis.db`.

Она хранит рассчитанные профили треков и используется для:

- поиска похожих треков;
- оценки следующего DJ-перехода;
- классификации переходов как SAFE, COMPATIBLE, RISKY или REJECTED;
- аудита сетов, созданных текущим генератором.

Текущая версия использует BPM, Camelot, waveform energy, жанр и длительность. База Engine DJ и музыкальные файлы не изменяются.
