# zmin_autoset

Портативное локальное приложение для сборки гармонических DJ-сетов из библиотеки Denon Engine DJ.

Версия: `0.4.6`

## Новое в 0.4.0

- Кнопка **«Создать плейлист Engine»**: создаёт плейлист в Engine DB (`m.db`) ссылками на исходные файлы (без копирования); папка в Engine задаётся рядом с кнопкой.

- [Полное описание на русском](README_RU.md)
- [Full English documentation](README_EN.md)

## Быстрый Старт

Положите папку рядом с музыкальной библиотекой и базой Engine DJ:

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

После запуска откроется локальная страница:

```text
http://127.0.0.1:8765/
```

HTML-страница работает через маленький локальный Python-сервер. Просто открыть `index.html` недостаточно: сервер нужен, чтобы читать базу Engine, запускать генератор и копировать аудиофайлы.

Готовые сеты складываются в `Music/Sets`. Служебные отчеты, backups, Python cache и локальные базы данных не публикуются в git.

Текущий рабочий provider: Denon Engine DJ. В приложении уже есть слой поиска других DJ-библиотек: rekordbox и Traktor могут определяться как кандидаты, но пока не парсятся.

---

# zmin_autoset

Portable local app for building harmonic DJ sets from a Denon Engine DJ library.

Version: `0.4.6`

## What's new in 0.4.0

- **Create Engine playlist** button: creates an Engine DB (`m.db`) playlist using links to original tracks (no file copy/rename); target Engine folder is set next to the button.

- [Full Russian documentation](README_RU.md)
- [Full English documentation](README_EN.md)

## Quick Start

Place the folder next to your music library and Engine DJ database:

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

The app opens a local browser UI at:

```text
http://127.0.0.1:8765/
```

The HTML page is served by a small local Python server. Opening `index.html` directly is not enough: the server reads the Engine database, starts the set builder, and copies audio files.

Generated sets are written to `Music/Sets`. Runtime reports, backups, Python caches, and local databases are intentionally ignored by git.

Current working provider: Denon Engine DJ. The app already has a discovery layer for other DJ libraries: rekordbox and Traktor can be detected as candidates, but they are not parsed yet.
