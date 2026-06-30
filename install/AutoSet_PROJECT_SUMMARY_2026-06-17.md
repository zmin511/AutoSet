# AutoSet: сводка проекта на 2026-06-17

## Статус аудита

- Проект определен как `AutoSet`.
- Дата аудита: `2026-06-17`.
- Это базовая версия аудита: предыдущие Markdown-аудиты по шаблону `*_PROJECT_SUMMARY_*`, `*_TECHNICAL_DETAILS_*`, `*_CHAT_HISTORY_DIGEST_*`, `*_TODO_AND_NEXT_STEPS_*`, `*_PROJECT_UPDATE_*` или `*_AUDIT_*` в доступных материалах не найдены.
- Найдено историческое Markdown-описание, но не аудит: `F:\zmin_autoset_versions\README.md`, проект `zmin_autoset`, версия `1.5.2`, дата файла `2026-05-20`.
- Текущий код находится в `F:\AutoSet`; рабочая музыкальная библиотека и результаты сетов находятся в `F:\Music`.
- Актуальный GitHub-репозиторий: `https://github.com/zmin511/AutoSet.git`.

## Краткое описание

`AutoSet` - локальное portable-приложение для Denon Engine DJ. Оно запускает Python HTTP-сервер и браузерный UI, читает SQLite-базу Engine DJ `Engine Library\Database2\m.db`, показывает треки, waveform, cue/loop, помогает подобрать гармоничный DJ-сет по BPM, Camelot, жанрам/стилям, длительности и оценочной энергии, а также создает локальные сет-папки и плейлисты внутри Engine DB.

## Цель проекта

Цель проекта - ускорить подготовку DJ-сетов на локальной медиатеке без облака и внешних аккаунтов как обязательного условия:

- выбирать опорный трек;
- видеть waveform, cue, loop и метаданные из Engine DB;
- строить последовательность треков по музыкальной совместимости;
- создавать папку с сетом, `playlist.m3u`, `playlist.csv`, `methodology.txt`;
- создавать плейлист в Engine DJ по ссылкам на существующие треки;
- редактировать жанры/теги и сохранять изменения не только в Engine DB, но и в самих аудиофайлах, если формат поддержан.

## Текущий статус

На дату аудита проект находится в рабочем состоянии версии `1.5.12`.

Подтверждено файлами и Git:

- `F:\AutoSet\set_app\set_app.py` содержит `APP_NAME = "AutoSet"` и `APP_VERSION = "1.5.12"`.
- `F:\AutoSet\README.md`, `README_RU.md`, `README_EN.md` и `CHANGELOG.md` обновлены до версии `1.5.12`.
- Последний коммит: `19051aa 2026-06-17 Update documentation version to 1.5.12`.
- Рабочее дерево `F:\AutoSet` на момент проверки было чистым.
- Remote: `origin https://github.com/zmin511/AutoSet.git`.

## Ключевые компоненты

- `F:\AutoSet\set_app\set_app.py` - локальный Python-сервер, REST-like API, интеграция с Engine DB, конфигурация путей, создание Engine-плейлистов, bulk-операции по жанрам, waveform/detail API.
- `F:\AutoSet\set_app\index.html` - браузерный интерфейс: папки, поиск, треки, waveform, player, жанры, генерация сетов/плейлистов.
- `F:\AutoSet\tools\engine_set_builder.py` - алгоритм подбора сетов.
- `F:\AutoSet\tools\engine_write_tags.py` - запись тегов в аудиофайлы через `mutagen`.
- `F:\AutoSet\tools\review_new_genres.py` - нормализация/предложение жанров для папки `New` и отчетность.
- `F:\AutoSet\tools\engine_config.py` - общие пути к `Music`, `m.db`, отчетам, backup и output.
- `F:\AutoSet\reports` - CSV-отчеты обновления тегов и жанров.
- `F:\Music\Sets` - готовые локальные результаты построения сетов.
- `F:\zmin_autoset_versions` - архивы старых версий и историческое описание проекта.

## Что уже реализовано

- Portable-запуск на Windows/macOS через `run_windows.cmd` и `run_mac.command`.
- Локальный UI на `http://127.0.0.1:8765/` с автоматическим выбором свободного порта при необходимости.
- Настройка путей к `Music`, `Engine Library` и `m.db`.
- Чтение Engine DB: `Track`, `PerformanceData`, `Playlist`, `PlaylistEntity`.
- Отображение треков, BPM, key/Camelot, жанра, длительности, энергии и доступности cue/loop.
- Цветная Engine-like waveform из `PerformanceData.overviewWaveFormData`.
- Чтение и показ `quickCues` и `loops`.
- Увеличенный waveform: overview + zoom waveform, beat-grid, cue/loop markers, playhead, zoom/scroll.
- Follow mode для zoom waveform с поведением ближе к Engine DJ.
- Read-only endpoints диагностики и waveform detail.
- Создание локального сета с копированием треков и файлами `playlist.m3u`, `playlist.csv`, `methodology.txt`.
- Создание Engine-плейлиста через `Playlist`/`PlaylistEntity`, в первую очередь по `Track.id`.
- Единое именование локального сета и Engine-плейлиста.
- Менеджер жанров/тегов для текущей папки: добавить, заменить, удалить тег; поддержка подпапок.
- `Rus` работает как отдельный допуск при подборе: без выбранного `Rus` русские треки исключаются из обычного сета.
- Онлайн-поиск стилей: Discogs, MusicBrainz, опционально Last.fm через `LASTFM_API_KEY` или `set_app\lastfm_api_key.txt`.
- Переработанные группы стилей: House, Techno/Deep Tech, Disco/Dance/Electronic, Trance/Progressive, Bass/Breaks/Garage, Chill/Lounge/Downtempo, Pop/Rock/Other.
- Запись waveform-energy в `Track.rating` Engine DJ по шкале `20/40/60/80/100`.
- Запись тегов в аудиофайлы:
  - MP3: `TCON`, `TBPM`, `TKEY`, `TXXX:AutoSet Styles`, `COMM`, `POPM` best-effort;
  - FLAC: `GENRE`, `BPM`, `INITIALKEY`/`KEY`, `AUTOSET_STYLES`, `RATING`;
  - M4A/MP4: genre, BPM, key/styles через доступные atoms/custom atoms; rating с warning;
  - WAV/AIFF: безопасный warning без рискованной записи.
- CLI dry-run для записи тегов, пример из чата: `python tools/engine_write_tags.py --file "..." --genre House --bpm 124 --key 3B --dry-run`.
- Отчеты по тегам и жанрам в CSV.

## Фактические артефакты на диске

- `F:\AutoSet` - актуальный проект.
- `F:\Engine Library\Database2\m.db` - Engine DB, размер около 296 МБ, дата изменения `2026-06-11`.
- В read-only проверке `m.db` найдено:
  - 10 таблиц;
  - `Track`: 11876 строк;
  - `PerformanceData`: 11876 строк;
  - `Playlist`: 1542 строки;
  - `PlaylistEntity`: 46890 строк.
- В `F:\Music` найдено 11998 аудиофайлов.
- В `F:\Music\Sets` найдено 12 папок сетов.
- В `F:\AutoSet\reports` найдено 12 файлов отчетов.
- В `F:\AutoSet\tag_backups` файлов backup на момент аудита не найдено.
- В `F:\Music\_autoset_tag_write_test` найден тестовый файл `autoset_tag_test.mp3`, созданный для проверки записи тегов.

## Что изменилось относительно исторического описания `zmin_autoset` 1.5.2

Так как предыдущего аудита не найдено, это не сравнение с аудитом. Это сравнение с историческим описанием `F:\zmin_autoset_versions\README.md`.

- Проект переименован из `zmin_autoset` в `AutoSet`.
- Локальная папка актуального проекта стала `F:\AutoSet`.
- GitHub-репозиторий переименован в `zmin511/AutoSet`.
- Версия поднята с `1.5.2` до `1.5.12`.
- Добавлены и развиты:
  - energy stars и запись рейтинга в Engine DB;
  - массовые инструменты жанров;
  - отдельный допуск `Rus`;
  - онлайн-поиск стилей;
  - новая группировка жанров;
  - подробный waveform endpoint и zoom waveform;
  - Follow behavior;
  - запись тегов в сами аудиофайлы через `mutagen`;
  - предупреждения UI о частичном успехе, если Engine DB обновлена, а файл нет.

## Готовые результаты

- Код и документация версии `1.5.12` находятся в `F:\AutoSet`.
- Последние изменения отправлены в GitHub `main`.
- Есть реальные CSV-отчеты по обновлению тегов/жанров.
- Есть реальные папки созданных сетов в `F:\Music\Sets`.
- Запись тегов в MP3 была проверена на тестовой копии: в чате указано, что `genre`, `key`, `autoset_styles`, `rating` записались и были прочитаны обратно через `mutagen`.

## Открытые вопросы

- Нет найденного полного тестового набора в репозитории; проверки из чатов в основном были Python compile, JS parse, ручные/endpoint проверки и Git diff.
- Не найдено в доступных материалах: формальная спецификация API AutoSet отдельным документом.
- Не найдено в доступных материалах: автотесты для записи тегов по форматам MP3/FLAC/M4A/WAV/AIFF.
- Не найдено в доступных материалах: отдельный механизм резервного копирования всех изменяемых аудиотегов перед массовой записью, кроме папки `tag_backups`, которая сейчас пуста.
- Для Last.fm нужен ключ; без него основной практический онлайн-источник - Discogs, затем MusicBrainz.
- MusicBrainz по чатам признан слабым источником точных стилей для электронной музыки.
- WAV/AIFF запись тегов сознательно не реализована из-за риска.

## Следующие шаги

1. Добавить формальные тесты для `engine_write_tags.py` на MP3/FLAC/M4A и на warning-сценарии.
2. Проверить массовую запись тегов на небольшой контролируемой папке с backup до и после.
3. Составить отдельную спецификацию API endpoints `set_app.py`.
4. Проверить кодировку русских README/CHANGELOG в разных терминалах и браузере.
5. Протестировать Engine-плейлист после пересканирования Engine DJ, чтобы убедиться, что теги из файлов не теряются.
6. Решить, нужен ли cache для high-resolution waveform: в коде упоминается будущий путь `set_app/cache/waveforms/<track_id>.json`.
