DJ Set Builder portable setup

What is already on this SSD:
- zmin_autoset/set_app/index.html: the one-page interface
- zmin_autoset/set_app/set_app.py: local server that reads Engine DJ and starts the builder
- zmin_autoset/tools/engine_set_builder.py: set generator
- Music/Sets: output folder

Windows:
1. Install Python 3.11+ from https://www.python.org/downloads/windows/ if the computer does not have Python.
2. Run zmin_autoset\set_app\run_windows.cmd.
3. The browser opens at http://127.0.0.1:8765/

macOS:
1. Install Python 3.11+ from https://www.python.org/downloads/macos/ if python3 is not available.
2. In Terminal run:
   chmod +x /Volumes/<SSD_NAME>/zmin_autoset/set_app/run_mac.command
3. Open zmin_autoset/set_app/run_mac.command.

Notes:
- The browser page itself cannot create sets without the small local Python server.
- No internet is needed after Python is installed.
- Keep this SSD structure together: zmin_autoset, Music, and Engine Library at the SSD root.
