import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4


class AudioTagBackupError(RuntimeError):
    """Raised when an audio file cannot be backed up and verified."""


def _relative_backup_path(file_path: Path, music_root: Path) -> Path:
    try:
        return file_path.resolve().relative_to(music_root.resolve())
    except (OSError, ValueError):
        return Path("external") / file_path.name


def create_verified_audio_backup(
    file_path: str | Path,
    backup_dir: str | Path,
    music_root: str | Path,
) -> Path:
    """Copy an audio file to a collision-safe path and verify its size."""
    source = Path(file_path)
    root = Path(backup_dir)
    relative = _relative_backup_path(source, Path(music_root))
    run_id = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{uuid4().hex[:10]}"
    destination = root / "audio_tags" / run_id / relative

    try:
        source_size = source.stat().st_size
        destination.parent.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source, destination)
        if not destination.is_file():
            raise AudioTagBackupError(f"Backup file was not created: {destination}")
        backup_size = destination.stat().st_size
        if backup_size != source_size:
            raise AudioTagBackupError(
                f"Backup size mismatch for {source}: expected {source_size}, got {backup_size}"
            )
    except AudioTagBackupError:
        raise
    except (OSError, shutil.Error) as exc:
        raise AudioTagBackupError(f"Audio backup failed for {source}: {exc}") from exc

    return destination
