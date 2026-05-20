# zmin_autoset

Версия: `1.5.2` · Changelog: `CHANGELOG.md`

`zmin_autoset` — локальное приложение (UI в браузере) для работы с библиотекой **Denon Engine DJ**:
ты выбираешь опорный трек, а приложение помогает собрать гармоничный сет и/или создать плейлист прямо в базе Engine — без облака и без внешних сервисов.

---

## Как работает (кратко)

Данные берутся из SQLite‑базы Engine:

```text
Engine Library/Database2/m.db
```

Используются таблицы:
- `Track` — путь к файлу, метаданные (artist/title/genre), BPM, key, length, доступность.
- `PerformanceData` — waveform и точки:
  - `overviewWaveFormData` — цветная overview‑вейвформа (как в Engine);
  - `quickCues` — `Cue 1..8` (позиции + подписи);
  - `loops` — `Loop 1..8` (start/end + подпись).

Сборка сета идёт по скорингу переходов:
- BPM: ограничения по окну (`BPM ±`) и шагу между соседними треками;
- Key: по кругу Camelot (`Camelot ±`);
- Жанр/стили: фильтр и “семейства” (house/techno/etc.);
- “Энергия”: оценивается по `overviewWaveFormData` и используется в выборе следующего трека.

---

## Как пользоваться (пошагово)

1) Укажи пути:
   - **Музыкальная библиотека** (`Music/`)
   - **База Engine DJ** (`m.db` или папка `Engine Library`)
   Нажми **Сохранить пути**.

2) Найди трек:
   - через поиск, либо открой папку в библиотеке.

3) Выбери опорный трек (клик по строке) и проверь его:
   - плеер + waveform: cue (сверху) и loops (снизу), можно скрабить мышью.

4) Настрой параметры:
   - **Роль трека**:
     - `Начало` — опорный трек используется как opener, дальше энергия плавно растёт;
     - `Кульминация` — опорный трек считается peak‑точкой, после неё энергия плавно снижается.
   - **Длительность** — желаемая длина сета в минутах.
   - **Camelot ±** — насколько далеко по кругу Camelot можно уходить (A↔B допускается, но с небольшим штрафом).
   - **BPM ±** — окно допустимых BPM относительно опорного трека.
   - **Стили для подбора** — дополнительные “корзины” жанров/поджанров, которые разрешены в подборе.

5) Выбери режим результата:
   - **Создать сет** — копирует треки в отдельную папку в `Music/Sets` и пишет `playlist.m3u`/`playlist.csv`.
   - **Создать плейлист** — создаёт плейлист в базе Engine (ссылками на треки, без копирования), и дополнительно пишет локальные `playlist.m3u`/`playlist.csv` для предпрослушивания.

6) Поле `Event` — путь папки в Engine, куда будет создан плейлист, например:
   - `Event`
   - `Event/Afro house`

---

## Что означает интерфейс

**Список треков**
- Синяя точка — у трека есть cue.
- Оранжевая точка — у трека есть loop.
- Если есть оба — точки две, одна над другой.

**Waveform**
- Цветная overview‑вейвформа как в Engine (RGB из `overviewWaveFormData`).
- Cue показываются сверху (с подписью и временем).
- Loop показываются снизу диапазоном (с подписью и временем старта).

---

Документация:
- Русский: `README_RU.md`
- English: `README_EN.md`

---

# zmin_autoset

Version: `1.5.2` · Changelog: `CHANGELOG.md`

`zmin_autoset` is a local (browser UI) companion app for **Denon Engine DJ**:
pick a reference track, then build a harmonic set and/or create an Engine playlist — fully offline.

## How it works (short)

Data is read from Engine’s SQLite DB:

```text
Engine Library/Database2/m.db
```

Tables used:
- `Track` — file path and metadata (artist/title/genre), BPM, key, length, availability.
- `PerformanceData` — waveform and markers:
  - `overviewWaveFormData` — RGB overview waveform (Engine-like);
  - `quickCues` — Cue 1..8 (positions + labels);
  - `loops` — Loop 1..8 (start/end + label).

Set building is a scoring process that balances:
- BPM (window + adjacent step limits),
- Camelot (wheel distance),
- genre/style filtering,
- “energy” derived from `overviewWaveFormData`.

## How to use

1) Configure paths (Music root + Engine DB) and save.
2) Find a track (search or folder browsing) and select it as the reference.
3) Use player + waveform (scrub with mouse, inspect cues/loops).
4) Set parameters:
   - Role: `Start` (energy rises) or `Peak` (energy releases after the peak),
   - Duration (minutes),
   - Camelot ±, BPM ±,
   - Style filters.
5) Output:
   - **Create set**: copies files into `Music/Sets/<run>/` + exports `playlist.m3u`/`playlist.csv`.
   - **Create playlist**: writes a playlist into Engine DB (links only) + also exports local `playlist.m3u`/`playlist.csv`.
6) `Event` is the Engine folder path to create the playlist under (e.g. `Event/Afro house`).

## UI notes

Track list:
- Blue dot: has cues.
- Orange dot: has loops.

Waveform:
- RGB overview waveform (Engine-like).
- Cues on top (label + time).
- Loops on bottom as ranges (label + start time).

Docs:
- Русский: `README_RU.md`
- English: `README_EN.md`
