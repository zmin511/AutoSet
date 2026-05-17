# zmin_autoset

Версия: `0.4.8`

`zmin_autoset` — портативное локальное приложение для:

- сборки гармонических DJ-сетов из библиотеки **Denon Engine DJ** (по BPM, Camelot/key, жанрам, длине);
- создания плейлистов **в базе Engine** (без копирования файлов);
- быстрого предпрослушивания результата через локальный `playlist.m3u` (ссылки на оригинальные треки).

Сервер и UI работают локально, без облака: приложение читает Engine DB (`m.db`), показывает треки в браузере и запускает сборку по выбранному опорному треку.

- Полное описание на русском: `README_RU.md`
- Full English documentation: `README_EN.md`

## Быстрый старт

Рекомендуемая структура на диске:

```text
<корень SSD или диска>/
  zmin_autoset/
  Music/
  Engine Library/
    Database2/
      m.db
```

Запуск:

- Windows: `zmin_autoset\run_windows.cmd`
- macOS: `zmin_autoset/run_mac.command`

UI откроется в браузере, обычно:

```text
http://127.0.0.1:8765/
```

Результаты:

- Сеты и локальные плейлисты пишутся в `Music/Sets` (каждый запуск — отдельная папка).
- Кнопка **«Создать сет»** копирует треки в папку результата и пишет `playlist.m3u` / `playlist.csv`.
- Кнопка **«Создать плейлист»** создаёт плейлист в Engine DB и дополнительно пишет локальные `playlist.m3u` / `playlist.csv` **без копирования** (можно открыть и прослушать вне Engine).

---

# zmin_autoset

Version: `0.4.8`

`zmin_autoset` is a portable local app for:

- building harmonic DJ sets from a **Denon Engine DJ** library (BPM, Camelot/key, genre, duration);
- creating playlists **inside Engine DB** (no file copy/rename);
- previewing results via a local `playlist.m3u` that links to the original tracks.

Everything runs locally (no cloud): the app reads the Engine DB (`m.db`), shows your library in a browser UI, and builds results from the selected reference track.

- Full Russian documentation: `README_RU.md`
- Full English documentation: `README_EN.md`

## Quick start

Recommended layout:

```text
<SSD or drive root>/
  zmin_autoset/
  Music/
  Engine Library/
    Database2/
      m.db
```

Run:

- Windows: `zmin_autoset\run_windows.cmd`
- macOS: `zmin_autoset/run_mac.command`

The UI opens in your browser (typically):

```text
http://127.0.0.1:8765/
```

Outputs:

- Sets and local playlists are written to `Music/Sets` (one folder per run).
- **Create set** copies tracks into the output folder and writes `playlist.m3u` / `playlist.csv`.
- **Create playlist** creates an Engine DB playlist and also writes local `playlist.m3u` / `playlist.csv` **without copying** (for previewing outside Engine).
