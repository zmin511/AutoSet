# zmin_autoset

`zmin_autoset` - портативное локальное приложение для сборки DJ-сетов на основе библиотеки Engine DJ.

Версия: `0.4.6`

## Новое в 0.4.0

- Кнопка **«Создать плейлист Engine»**: создаёт плейлист в Engine DB (`m.db`) **ссылками на исходные файлы**, без копирования/переименования (папку в Engine можно указать рядом с кнопкой).

Приложение читает базу Engine DJ, показывает музыку в браузере, помогает выбрать опорный трек и собирает гармонический сет по BPM, Camelot/key, жанрам, битрейту и длительности. Готовый сет копируется в отдельную папку вместе с `playlist.m3u` и `playlist.csv`.

Текущий рабочий provider: Denon Engine DJ.

В приложении заложен слой поиска разных DJ-библиотек. Сейчас оно умеет находить кандидаты rekordbox и Traktor, но полноценно парсит и использует только Denon Engine DJ. Для Pioneer rekordbox и Native Instruments Traktor нужен отдельный адаптер, потому что у них другие файлы, поля и формат хранения тональности/BPM/пути.

## Как Это Работает

Engine DJ хранит основную информацию о треках в SQLite-базе:

```text
Engine Library/Database2/m.db
```

`zmin_autoset` читает оттуда:

- путь к файлу;
- artist/title/filename;
- BPM;
- key, из которого считается Camelot;
- genre;
- bitrate;
- length;
- доступность трека.

## Другие DJ-Библиотеки

Сейчас рабочая схема такая:

```text
Provider: Denon Engine DJ
Database: Engine Library/Database2/m.db
Status: supported
```

Приложение также проверяет типовые места для других библиотек:

- Pioneer rekordbox: USB/export-кандидаты вроде `PIONEER/rekordbox/export.pdb`, а также локальные `master.db`;
- Native Instruments Traktor: `collection.nml` в папках Traktor.

Если такие файлы найдены, приложение может показать их как `detected_not_supported`. Это значит: библиотека обнаружена, но сет пока нельзя строить из неё напрямую.

Почему нельзя просто “подставить другую базу”:

- у разных программ разные имена таблиц и полей;
- Traktor часто хранит коллекцию как XML/NML, а не как SQLite;
- rekordbox может использовать разные форматы локальной и USB-библиотеки;
- по-разному записываются key/Camelot, пути, rating, availability и анализ.

Правильный путь - adapter layer:

```text
Denon Engine DB  -> common Track model -> zmin_autoset algorithm
rekordbox DB/PDB -> common Track model -> zmin_autoset algorithm
Traktor NML      -> common Track model -> zmin_autoset algorithm
```

Этот слой уже начат: интерфейс и API теперь знают, какой provider активен, и могут показывать найденные библиотеки. Следующий шаг - добавить отдельные parser/adapter для rekordbox и Traktor.

Реальные аудиофайлы приложение трогает только тогда, когда нужно:

- проиграть preview в браузере;
- обновить теги;
- скопировать выбранные треки в готовый сет.

## Куда Класть Папку

Рекомендуемая структура на SSD или диске:

```text
G:/
  zmin_autoset/
  Music/
  Engine Library/
    Database2/
      m.db
```

Важно: `zmin_autoset`, `Music` и `Engine Library` должны лежать рядом, на одном уровне. Приложение вычисляет корень диска относительно своей папки и ожидает такую структуру.

Если диск называется иначе, например `D:/` или `/Volumes/DJSSD/`, структура остается такой же:

```text
<корень диска>/
  zmin_autoset/
  Music/
  Engine Library/
```

## Как Скопировать На Другой Компьютер

Скопируйте на SSD или внешний диск эти папки:

```text
zmin_autoset/
Music/
Engine Library/
```

После копирования откройте Engine DJ и убедитесь, что библиотека видит треки. Если Engine DJ заново анализирует или обновляет пути, дождитесь окончания анализа, затем запускайте `zmin_autoset`.

## Запуск На Windows

Самый простой запуск:

```cmd
zmin_autoset\run_windows.cmd
```

Также можно запускать внутренний файл:

```cmd
zmin_autoset\set_app\run_windows.cmd
```

Скрипт пробует:

1. локальный Python в `zmin_autoset\python-windows\python.exe`, если вы его положили рядом;
2. системный `py -3`;
3. системный `python`.

После запуска откроется браузер:

```text
http://127.0.0.1:8765/
```

## Запуск На macOS

В Terminal один раз дайте право на запуск:

```sh
chmod +x /Volumes/<SSD_NAME>/zmin_autoset/run_mac.command
chmod +x /Volumes/<SSD_NAME>/zmin_autoset/set_app/run_mac.command
```

Потом запускайте:

```sh
/Volumes/<SSD_NAME>/zmin_autoset/run_mac.command
```

или двойным кликом по `run_mac.command`.

Нужен Python 3.11+ или новее. Если `python3` не установлен, поставьте Python с https://www.python.org/downloads/macos/.

## Можно Ли Открыть HTML Напрямую

Только для просмотра верстки. Для реальной работы нужно запускать Python-сервер.

Почему:

- браузер сам по себе не может читать SQLite-базу Engine;
- браузер не может безопасно копировать файлы в `Music/Sets`;
- генератор сетов запускается локальным Python-процессом.

Правильный запуск всегда через:

```text
run_windows.cmd
run_mac.command
```

## Основные Папки

`set_app/`

Локальное web-приложение:

- `index.html` - интерфейс;
- `set_app.py` - локальный HTTP-сервер;
- `run_windows.cmd` - запуск на Windows;
- `run_mac.command` - запуск на macOS.

`tools/`

Скрипты для работы с Engine DJ и файлами:

- `engine_set_builder.py` - основной генератор сетов;
- `engine_db_playlist.py` - чтение Engine DB и простые плейлисты;
- `engine_write_tags.py` - запись BPM/key/bitrate из Engine в теги файлов;
- `review_new_genres.py` - классификация новых треков по жанрам/style/family;
- `tag_from_musicbrainz.py` - дополнительное обогащение жанров через MusicBrainz/iTunes;
- `make_start_set*.cmd` и `make_peak_set*.cmd` - быстрые запускалки сборки сетов;
- `refresh_tags_*.cmd` - обновление тегов;
- `review_new_genres_*.cmd` - проверка и применение жанровых решений.

`reports/`

Сюда складываются CSV-отчеты после обновления тегов и жанров. Папка не публикуется в git.

`tag_backups/`

Сюда складываются backup-копии аудиофайлов перед записью тегов. Папка не публикуется в git.

`Music/Sets/`

Сюда приложение складывает готовые сеты. Эта папка находится рядом с `zmin_autoset`, внутри вашей музыкальной библиотеки.

## Типовой Рабочий Процесс

1. Добавьте новые треки в `Music/New` или другую папку внутри `Music`.
2. Импортируйте и проанализируйте треки в Engine DJ.
3. Запустите `zmin_autoset`.
4. Выберите папку или найдите трек через поиск.
5. Выберите опорный трек.
6. Выберите роль трека: начало или кульминация.
7. Укажите длительность, шаг Camelot и BPM-окно.
8. Нажмите “Создать сет”.
9. Заберите результат из `Music/Sets/...`.

## Что Получается На Выходе

Для каждого сета создается отдельная папка:

```text
Music/Sets/<timestamp>_<role>_<track-name>/
  01 - Track Name (124BPM-8A).mp3
  02 - Track Name (125BPM-9A).mp3
  playlist.m3u
  playlist.csv
```

В скобках в имени файла пишется BPM и Camelot-тональность. Это сделано специально, чтобы быстро проверять, как алгоритм двигается по темпу и тональности.

`playlist.m3u` можно открыть в плеере.

`playlist.csv` удобно смотреть как таблицу: порядок, artist, title, length, BPM, Camelot, genre, bitrate, исходный путь.

## Обслуживание Библиотеки

В интерфейсе есть кнопка обновления тегов текущей папки. Она запускает tools-скрипты и может записывать в аудиофайлы:

- BPM;
- key/Camelot;
- служебный bitrate tag;
- жанровые решения, если используется соответствующий сценарий.

Перед массовым изменением тегов лучше держать backup. Для этого есть `tag_backups/`.

## Что Не Нужно Публиковать В Git

В репозитории должны быть только код и документация.

Не нужно коммитить:

- `reports/`;
- `tag_backups/`;
- `__pycache__/`;
- локальные `.db` и `.sqlite`;
- `Music/`;
- `Engine Library/`;
- локальный portable Python, если он большой.

Это уже учтено в `.gitignore`.

## Минимальные Требования

- Python 3.11+.
- Engine DJ library с `Engine Library/Database2/m.db`.
- Музыка в папке `Music`.
- Современный браузер.

Интернет после установки Python не нужен, кроме сценариев, где вы отдельно запускаете `tag_from_musicbrainz.py`.
