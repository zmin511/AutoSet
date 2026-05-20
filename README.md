# zmin_autoset

Версия: `1.5.2`

`zmin_autoset` — локальное приложение для **Denon Engine DJ**: быстро отобрать опорный трек, собрать гармоничный сет и/или создать плейлист прямо в базе Engine.

**Что умеет**
- Список треков из `Engine Library/Database2/m.db` + просмотр папок `Music/` (без облака).
- Сборка сета по BPM/Camelot/жанру/длине + учёт “энергии” из `overviewWaveFormData`.
- Создание плейлиста в Engine DB (ссылками, без копирования файлов) и локальный `playlist.m3u`/`playlist.csv`.
- Встроенный плеер + waveform “как в Engine”: цветная overview‑вейвформа, cue/loop метки, скраб мышью.

Документация:
- Русский: `README_RU.md`
- English: `README_EN.md`

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

UI откроется в браузере (обычно):
```text
http://127.0.0.1:8765/
```

Результаты:
- Сеты и локальные плейлисты пишутся в `Music/Sets` (каждый запуск — отдельная папка).

---

# zmin_autoset

Version: `1.5.2`

`zmin_autoset` is a local app for **Denon Engine DJ**: pick a reference track, build a harmonic set and/or create an Engine playlist.

**Features**
- Browse tracks from `Engine Library/Database2/m.db` + browse `Music/` folders (no cloud).
- Build sets using BPM/Camelot/genre/duration + “energy” from `overviewWaveFormData`.
- Create playlists inside Engine DB (links only, no file copy) + local `playlist.m3u`/`playlist.csv`.
- Built-in player + Engine-like waveform: RGB overview waveform, cue/loop markers, mouse scrubbing.

Docs:
- Русский: `README_RU.md`
- English: `README_EN.md`

## Quick start

Recommended layout:

```text
<drive root>/
  zmin_autoset/
  Music/
  Engine Library/
    Database2/
      m.db
```

Run:
- Windows: `zmin_autoset\run_windows.cmd`
- macOS: `zmin_autoset/run_mac.command`

Open UI (usually):
```text
http://127.0.0.1:8765/
```

Outputs:
- Sets and local playlists are written to `Music/Sets` (one folder per run).

