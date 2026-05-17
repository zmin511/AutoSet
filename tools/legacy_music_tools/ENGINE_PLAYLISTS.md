# Engine playlists (в базе данных)

Этот режим создаёт плейлист прямо в Engine Library DB (SQLite), **без копирования/перемещения** файлов: в плейлисте просто появляются ссылки на уже импортированные в Engine треки, а порядок задаётся таблицей `PlaylistEntity` (через поле `nextEntityId`, как в примере `Event/zz`).

## Скрипт

`F:\Music\tools\engine_playlist_db.py`

## Примеры

Проверка (ничего не пишет в DB):

```powershell
python F:\Music\tools\engine_playlist_db.py `
  --db "F:\Engine Library\Database2\m.db" `
  --music-root "F:\Music" `
  --folder "Event" `
  --title "A2Z" `
  --csv "F:\Music\Sets\...\playlist.csv" `
  --dry-run
```

Создание плейлиста (пишет в DB):

```powershell
python F:\Music\tools\engine_playlist_db.py `
  --db "F:\Engine Library\Database2\m.db" `
  --music-root "F:\Music" `
  --folder "Event" `
  --title "A2Z" `
  --m3u "F:\Music\Sets\...\playlist.m3u"
```

## Важно

- Треки **должны уже быть импортированы в Engine**, иначе их не получится найти в таблице `Track`.
- `Track.path` в Engine обычно хранится как `../Music/<...>` (относительно папки `Engine Library`), поэтому нужен правильный `--music-root`.
- На время записи в DB лучше закрывать Engine (чтобы не было конфликтов/перезаписи).

