# AutoSet

Version: `1.5.15` | Changelog: `CHANGELOG.md`

## Русское описание

`AutoSet` - локальное portable-приложение для **Denon Engine DJ**. Оно
помогает собрать гармоничный DJ-сет от выбранного опорного трека, проверить
трек по waveform/cue/loop и создать плейлист прямо в базе Engine без облака,
аккаунтов и внешних сервисов.

### Что умеет

- Выбор опорного трека из библиотеки Engine или папок `Music/`.
- Подбор сета по BPM, Camelot, жанру/стилю, длительности и примерной энергии.
- Две роли опорного трека: `Начало` и `Кульминация`.
- Прослушивание трека во встроенном плеере.
- Отображение Engine-like waveform, cue и loop.
- Создание папки с копиями треков, `playlist.m3u`, `playlist.csv`, `methodology.txt`.
- Создание плейлиста прямо в Engine DB ссылками на существующие треки.
- Обновление BPM/key/bitrate и DJ-жанровых тегов для выбранной папки.

### Как работает

Главный источник данных - SQLite-база Engine:

```text
Engine Library/Database2/m.db
```

Приложение читает:

- `Track` - путь к файлу, artist/title/genre, BPM, key, length, bitrate;
- `PerformanceData.overviewWaveFormData` - цветную overview-waveform;
- `PerformanceData.quickCues` - Cue 1..8;
- `PerformanceData.loops` - Loop 1..8.

Алгоритм подбора оценивает соседние переходы: разницу BPM, расстояние по
числам Camelot, близость жанров, энергию waveform, длину, битрейт и похожие
версии одного трека. A/B не увеличивает Camelot-расстояние.

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
set_app/set_app.py          локальный сервер, API, интеграция с Engine DB
set_app/index.html          браузерный интерфейс
tools/engine_set_builder.py алгоритм построения сета
tools/engine_config.py      общая конфигурация путей
tools/engine_write_tags.py  запись Engine BPM/key/bitrate в ID3-теги
tools/review_new_genres.py  нормализация жанров, семейств и DJ-тегов
```

Полная русская документация: `README_RU.md`

---

## English Description

`AutoSet` is a local portable companion app for **Denon Engine DJ**. It
helps build a harmonic DJ set from a selected reference track, inspect tracks
with waveform/cue/loop data, and create playlists directly inside the Engine
database without cloud services, accounts, or external services.

### Features

- Pick a reference track from the Engine library or `Music/` folders.
- Build a set by BPM, Camelot key, genre/style, duration, and estimated energy.
- Show estimated track energy as stars and optionally write it to Engine DJ `Track.rating`.
- Use the reference track as `Start` or `Peak`.
- Preview tracks in the built-in player.
- Render Engine-like waveform, cues, and loops.
- Create a copied set folder with `playlist.m3u`, `playlist.csv`, `methodology.txt`.
- Create an Engine DB playlist with links to existing tracks.
- Refresh BPM/key/bitrate and DJ genre tags for a selected folder.
- Add, replace, and remove genre tags for the current folder or folder plus subfolders.
- Write estimated waveform energy into Engine DJ star ratings for the selected folder or the whole `Music` library.

### How It Works

The main data source is the Engine SQLite database:

```text
Engine Library/Database2/m.db
```

The app reads:

- `Track` - file path, artist/title/genre, BPM, key, length, bitrate;
- `PerformanceData.overviewWaveFormData` - RGB overview waveform;
- `PerformanceData.quickCues` - Cue 1..8;
- `PerformanceData.loops` - Loop 1..8.

The builder scores adjacent transitions by BPM delta, Camelot distance, genre
distance by number, genre distance, waveform energy, track length, bitrate, and
near-duplicate versions of the same song. A/B does not increase Camelot distance.

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
set_app/set_app.py          local server, API, Engine DB integration
set_app/index.html          browser interface
tools/engine_set_builder.py set-building algorithm
tools/engine_config.py      shared path configuration
tools/engine_write_tags.py  writes Engine BPM/key/bitrate into ID3 tags
tools/review_new_genres.py  normalizes genres, families, and DJ tags
```

Full English documentation: `README_EN.md`
