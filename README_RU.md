# zmin_autoset

Версия: `1.5.2`

`zmin_autoset` — локальное приложение (UI в браузере) для работы с библиотекой **Denon Engine DJ**:

- собрать гармоничный DJ‑сет по опорному треку;
- создать плейлист прямо в базе Engine (ссылками на треки, без копирования);
- визуально проверить трек по waveform + cue/loop.

## Как это устроено

Engine хранит данные в SQLite:

```text
Engine Library/Database2/m.db
```

`zmin_autoset` читает оттуда треки и `PerformanceData`:
- `overviewWaveFormData` — цветная overview‑вейвформа (как в Engine);
- `quickCues` — подписи и позиции Cue 1..8;
- `loops` — Loop 1..8 (start/end + подпись).

## Возможности

**1) Браузер треков**
- просмотр папок `Music/` и быстрый поиск по библиотеке;
- таблица с BPM, Camelot, длиной;
- индикаторы наличия cue/loop у трека.

**2) Плеер и waveform**
- play/pause, громкость;
- скраб по waveform мышью;
- cue (сверху) и loop (снизу) с подписями и временем.

**3) Создание сета / плейлиста**
- сборка сета по BPM/Camelot/жанру/длине;
- энергия трека берётся из `overviewWaveFormData` и используется в скоринге переходов;
- плейлист можно создать в Engine DB и параллельно получить локальные `playlist.m3u`/`playlist.csv`.

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
- `Music/Sets/<имя_запуска>/playlist.m3u`
- `Music/Sets/<имя_запуска>/playlist.csv`

