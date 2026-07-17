"""Transactional, backed-up writes to an Engine DJ SQLite database."""

from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar
from urllib.parse import urlencode, urlsplit, urlunsplit


T = TypeVar("T")

_ENGINE_WRITE_LOCK = threading.Lock()
_LOCKED_MARKERS = ("database is locked", "database table is locked", "database is busy")
_CORRUPT_MARKERS = ("file is not a database", "database disk image is malformed")


class EngineDBWriteError(Exception):
    """Base exception carrying a stable API-facing reason code."""

    code = "write_failed"

    def __init__(self, message: str, *, backup_path: Path | None = None) -> None:
        super().__init__(message)
        self.backup_path = backup_path


class EngineDBLockedError(EngineDBWriteError):
    code = "db_locked"


class EngineDBWriteBusyError(EngineDBWriteError):
    code = "write_busy"


class EngineDBBackupError(EngineDBWriteError):
    code = "backup_failed"


class EngineDBIntegrityError(EngineDBWriteError):
    code = "integrity_check_failed"


class EngineDBOperationError(EngineDBWriteError):
    code = "write_failed"


def _is_locked_error(exc: BaseException) -> bool:
    message = str(exc).casefold()
    return any(marker in message for marker in _LOCKED_MARKERS)


def _is_corrupt_error(exc: BaseException) -> bool:
    message = str(exc).casefold()
    return any(marker in message for marker in _CORRUPT_MARKERS)


def _safe_operation_name(operation: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(operation or "engine_write")).strip("_")
    return name[:64] or "engine_write"


def _sqlite_file_uri(path: Path, mode: str) -> str:
    """Build an encoded cross-platform SQLite file URI with an explicit mode."""

    parts = urlsplit(path.expanduser().resolve().as_uri())
    return urlunsplit(parts._replace(query=urlencode({"mode": mode})))


def _backup_path(backup_dir: Path, operation: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    suffix = uuid.uuid4().hex[:10]
    return backup_dir / f"{stamp}_{_safe_operation_name(operation)}_{suffix}.db"


def _create_verified_backup(
    db_path: Path,
    backup_dir: Path,
    operation: str,
    *,
    sqlite_timeout: float,
) -> Path:
    source = None
    destination = None
    backup_path = None
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = _backup_path(backup_dir, operation)
        source = sqlite3.connect(
            _sqlite_file_uri(db_path, "ro"),
            timeout=sqlite_timeout,
            uri=True,
        )
        destination = sqlite3.connect(str(backup_path), timeout=sqlite_timeout)
        source.backup(destination)
        destination.commit()
    except Exception as exc:
        if _is_corrupt_error(exc):
            raise EngineDBIntegrityError(str(exc), backup_path=backup_path) from exc
        raise EngineDBBackupError(str(exc), backup_path=backup_path) from exc
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()

    check = None
    try:
        check = sqlite3.connect(str(backup_path), timeout=sqlite_timeout)
        rows = check.execute("PRAGMA integrity_check").fetchall()
    except Exception as exc:
        raise EngineDBIntegrityError(str(exc), backup_path=backup_path) from exc
    finally:
        if check is not None:
            check.close()

    messages = [str(row[0]) for row in rows]
    if messages != ["ok"]:
        detail = "; ".join(messages[:10]) or "integrity_check returned no result"
        raise EngineDBIntegrityError(detail, backup_path=backup_path)
    return backup_path


def safe_engine_db_write(
    db_path: str | Path,
    backup_dir: str | Path,
    operation: str,
    write: Callable[[sqlite3.Connection, Path], T],
    *,
    lock_timeout: float = 1.0,
    sqlite_timeout: float = 1.0,
) -> tuple[T, Path]:
    """Run one Engine DB write after taking a verified SQLite backup."""

    resolved_db = Path(db_path)
    resolved_backup_dir = Path(backup_dir)
    acquired = _ENGINE_WRITE_LOCK.acquire(timeout=max(0.0, float(lock_timeout)))
    if not acquired:
        raise EngineDBWriteBusyError("Another Engine DB write is already running")

    connection = None
    backup_path = None
    try:
        try:
            connection = sqlite3.connect(
                _sqlite_file_uri(resolved_db, "rw"),
                timeout=sqlite_timeout,
                uri=True,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            if _is_locked_error(exc):
                raise EngineDBLockedError(str(exc)) from exc
            if _is_corrupt_error(exc):
                raise EngineDBIntegrityError(str(exc)) from exc
            raise EngineDBOperationError(str(exc)) from exc

        backup_path = _create_verified_backup(
            resolved_db,
            resolved_backup_dir,
            operation,
            sqlite_timeout=sqlite_timeout,
        )
        try:
            result = write(connection, backup_path)
            connection.commit()
            return result, backup_path
        except EngineDBWriteError:
            raise
        except Exception as exc:
            if isinstance(exc, sqlite3.Error) and _is_locked_error(exc):
                raise EngineDBLockedError(str(exc), backup_path=backup_path) from exc
            raise EngineDBOperationError(str(exc), backup_path=backup_path) from exc
    except Exception:
        if connection is not None:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
        raise
    finally:
        try:
            if connection is not None:
                connection.close()
        finally:
            _ENGINE_WRITE_LOCK.release()
