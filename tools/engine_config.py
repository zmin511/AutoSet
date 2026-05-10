import json
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parent.parent
DISK_ROOT = REPO_DIR.parent
CONFIG_PATH = REPO_DIR / "set_app" / "paths.json"

FALLBACK_MUSIC_ROOT = DISK_ROOT / "Music" if (DISK_ROOT / "Music").exists() else DISK_ROOT
FALLBACK_DB_PATH = DISK_ROOT / "Engine Library" / "Database2" / "m.db"
FALLBACK_REPORT_DIR = REPO_DIR / "reports"
FALLBACK_BACKUP_DIR = REPO_DIR / "tag_backups"
FALLBACK_OUT_DIR = FALLBACK_MUSIC_ROOT / "Sets"


def _default_db_path():
    for candidate in (
        DISK_ROOT / "Engine Library" / "Database2" / "m.db",
        DISK_ROOT / "Engine" / "Database2" / "m.db",
        DISK_ROOT / "Engine Library" / "Database" / "m.db",
        DISK_ROOT / "Engine" / "Database" / "m.db",
        FALLBACK_MUSIC_ROOT / "Engine Library" / "Database2" / "m.db",
        FALLBACK_MUSIC_ROOT / "Engine" / "Database2" / "m.db",
    ):
        if candidate.exists():
            return candidate
    return FALLBACK_DB_PATH


def load_paths():
    paths = {
        "music_root": str(FALLBACK_MUSIC_ROOT),
        "db_path": str(_default_db_path()),
        "report_dir": str(FALLBACK_REPORT_DIR),
        "backup_dir": str(FALLBACK_BACKUP_DIR),
        "out_dir": str(FALLBACK_OUT_DIR),
    }
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in ("music_root", "db_path"):
                    value = str(data.get(key) or "").strip()
                    if value:
                        paths[key] = value
                sets_dir = str(data.get("sets_dir") or "").strip()
                if sets_dir:
                    paths["out_dir"] = sets_dir
                else:
                    paths["out_dir"] = str(Path(paths["music_root"]) / "Sets")
        except Exception:
            pass
    return paths


PATHS = load_paths()
