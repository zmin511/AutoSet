AutoSet portable setup / портативная установка

Version / версия: 0.2.0

Recommended drive layout:

<drive root>/
  AutoSet/
  Music/
  Engine Library/
    Database2/
      m.db

Рекомендуемая структура:

<корень диска>/
  AutoSet/
  Music/
  Engine Library/
    Database2/
      m.db

Windows:
1. Install Python 3.11+ if needed.
2. Run AutoSet\run_windows.cmd.
3. The browser opens at http://127.0.0.1:8765/

macOS:
1. Install Python 3.11+ if needed.
2. Run once:
   chmod +x /Volumes/<SSD_NAME>/AutoSet/run_mac.command
   chmod +x /Volumes/<SSD_NAME>/AutoSet/set_app/run_mac.command
3. Open AutoSet/run_mac.command.

Русский:
1. Если Python 3.11+ не установлен, установите его.
2. Windows: запустите AutoSet\run_windows.cmd.
3. macOS: дайте права chmod +x и запустите AutoSet/run_mac.command.
4. Интерфейс откроется в браузере на http://127.0.0.1:8765/

Important:
- Do not open set_app/index.html directly for real work. It needs the local Python server.
- Keep AutoSet, Music, and Engine Library together at the same level.
- Read README_RU.md or README_EN.md for full documentation.

Важно:
- Для реальной работы не открывайте set_app/index.html напрямую. Нужен локальный Python-сервер.
- Держите AutoSet, Music и Engine Library рядом, на одном уровне.
- Полное описание: README_RU.md и README_EN.md.
