# AutoSet: TODO и следующие шаги на 2026-06-30

## Текущая точка

`AutoSet` находится на линии `1.5.24`, последний коммит `5c144a2`, но рабочее дерево `F:\AutoSet` не чистое. Это главный практический факт для продолжения: перед новыми задачами нужно понять, какие изменения уже сделаны, какие из них пользовательские, какие временные, а какие нужно довести до коммита.

## Приоритет P0

### 1. Разобрать незакоммиченное состояние `F:\AutoSet`

Текущий status:

```text
 M .gitignore
 M set_app/index.html
 M set_app/run_windows.cmd
 M set_app/set_app.py
?? debug/
?? install/AutoSet_AUDIT_2026-06-17.zip
?? install/AutoSet_CHAT_HISTORY_DIGEST_2026-06-17.md
?? install/AutoSet_PROJECT_SUMMARY_2026-06-17.md
?? install/AutoSet_PROJECT_UPDATE_2026-06-17.md
?? install/AutoSet_TECHNICAL_DETAILS_2026-06-17.md
?? install/AutoSet_TODO_AND_NEXT_STEPS_2026-06-17.md
?? set_app/index1.html
?? set_app/set_app1.py
```

Что проверить:

- кто и зачем создал `set_app/index1.html` и `set_app/set_app1.py`;
- являются ли `debug/` и `install/AutoSet_*_2026-06-17.*` локальными артефактами или их надо игнорировать;
- нужно ли коммитить `.gitignore` с `set_app/track_marks/`;
- нужно ли коммитить новый `run_windows.cmd`;
- готов ли большой WebAudio/media playback diff в `index.html` к тестированию/коммиту.

### 2. Протестировать UI `1.5.24` плюс незакоммиченный audio слой

Проверить в браузере:

- открытие приложения;
- загрузка библиотеки;
- поиск и browser;
- выбор трека;
- Play/Pause;
- seek до Play;
- `/media` playback;
- WebAudio fallback, если он реально нужен;
- `/api/media-check`;
- громкость;
- overview waveform;
- zoom waveform;
- Follow;
- отсутствие JS errors.

### 3. Проверить Track Prep end-to-end

Проверить на копии/безопасном треке:

- загрузка существующего JSON;
- создание marks;
- создание loops;
- snap Beat/Bar/16/32;
- selected mark и loop-from-mark;
- Save/Reset;
- Suggest Marks;
- Accept/Clear suggestions;
- Batch Suggest Preview;
- Export selected track marks/loops to Engine DJ;
- backup `m.db`;
- conflict/overwrite behavior.

### 4. Не делать массовых операций с аудио и Engine DB без dry-run

Перед любым массовым применением:

- dry-run;
- отчет CSV/JSON;
- выборка нескольких строк;
- backup, если меняются файлы или Engine DB;
- явное подтверждение пользователя.

## Приоритет P1

### 5. Закрепить launcher/dependency strategy

`run_windows.cmd` сейчас изменен и умеет:

- выбирать portable `python-windows`, `py -3`, затем `python`;
- проверять `mutagen`;
- ставить `requirements.txt`;
- возвращать exit code.

Нужно:

- проверить на чистой среде;
- проверить, что скрипт не ломает fallback на другой Python;
- решить, коммитить ли это отдельным коммитом;
- обновить README, если стратегия принята.

### 6. Добавить минимальные автоматические smoke-тесты

Кандидаты:

- Python compile для `set_app.py` и `tools/*.py`;
- извлечение inline JS из `index.html` и `node --check`;
- endpoint smoke: `/api/config`, `/api/media-check`, `/api/track_waveform_detail`;
- Track Prep JSON read/write на временном файле;
- `engine_cue_loop_codec.py --help`;
- read-only decode на debug DB, если debug DB остается локальным тестовым материалом.

### 7. Уточнить политику хранения audit-документов

Сейчас:

- предыдущий аудит `2026-06-17` найден в `F:\AutoSet\install` как untracked;
- новый аудит `2026-06-30` создан в `F:\Music`;
- старые файлы удалять нельзя.

Рекомендация:

- выбрать один постоянный каталог для audit-документов, например `F:\Music` или `F:\AutoSet\docs\audits`;
- не переносить старые файлы без явного решения пользователя;
- в следующем аудите искать оба места.

### 8. Документировать endpoints

Нужно отдельное API reference:

- путь;
- метод;
- параметры;
- пример ответа;
- write/read-only;
- какие файлы или DB меняет;
- какие safety checks выполняет.

### 9. Упорядочить отчеты

`F:\AutoSet\reports` содержит 50 элементов. Нужно:

- добавить summary-файл последнего прогона;
- фиксировать counts: matched, updated, skipped, warnings, errors;
- не смешивать genre reports и tag write reports без индекса;
- решить retention policy.

## Приоритет P2

### 10. Проверить README/CHANGELOG на кодировку

В PowerShell часть русских строк отображается как mojibake. Нужно:

- проверить фактический UTF-8 в редакторе/браузере/GitHub;
- если файлы повреждены, восстановить из GitHub или вручную;
- если это только консоль, добавить примечание для Windows terminal.

### 11. Разобрать временные helper-скрипты в `F:\Music`

В корне `F:\Music` есть:

- `autoset_step_*.py`;
- `autoset_patch_*.py`;
- `autoset_node_check.py`;
- `autoset_test_write_script.py`.

Они патчат `F:\AutoSet` и похожи на рабочие временные артефакты. Удалять нельзя без разрешения. Нужно решить:

- оставить как историю;
- перенести в `F:\AutoSet\debug`;
- добавить README-заметку;
- удалить после подтверждения пользователя.

### 12. Проверить `codex_dj_meta.sqlite`

Старые чаты описывали `F:\Music\Engine Library\codex_dj_meta.sqlite`, но сейчас этот файл не найден. Нужно:

- понять, нужна ли эта база в актуальной архитектуре;
- если нужна, восстановить/пересоздать;
- если не нужна, убрать ссылки из документации и старых workflow.

## Риски

- Нечистое git-дерево может привести к потере пользовательских изменений, если делать reset/revert. Нельзя откатывать без явного запроса.
- Track Prep export пишет в Engine DB; ошибка codec/raw position может испортить cues/loops, поэтому только с backup.
- Массовая запись тегов в аудиофайлы необратима без backup.
- UI сейчас монолитный `index.html`; layout-правки уже вызывали регрессии.
- Audio/WebAudio слой в незакоммиченном diff большой и требует браузерной проверки.
- Старые audit-файлы лежат в `install` как untracked и могут случайно попасть в commit.

## Рекомендуемый порядок дальнейших действий

1. Сохранить текущий аудит `2026-06-30` и ZIP.
2. Открыть `F:\AutoSet` и зафиксировать текущий `git status`.
3. Сделать отдельный review незакоммиченного diff без правок.
4. Решить, что делать с WebAudio/media playback слоем.
5. Прогнать UI smoke-тест в браузере.
6. Если слой принят, оформить один или несколько маленьких коммитов.
7. После чистого дерева продолжать новые задачи.
8. Перед следующим аудитом сравнивать с файлами `AutoSet_*_2026-06-30.md`.

## Что проверить перед следующим этапом

- Есть ли новые коммиты после `5c144a2`.
- Изменился ли `APP_VERSION`.
- Стал ли `git status` чистым.
- Появились ли новые `track_marks`.
- Появились ли новые backups Engine DB.
- Были ли новые `engine_write_tags_*` reports.
- Изменилось ли количество аудиофайлов в `F:\Music`.
- Остались ли старые audit-файлы в `F:\AutoSet\install`.
