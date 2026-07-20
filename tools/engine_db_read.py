"""Read-only connections to an Engine DJ SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union


PathLike = Union[str, Path]


def open_engine_db_read_only(
    db_path: PathLike,
    *,
    timeout: float = 5.0,
) -> sqlite3.Connection:
    """Open an existing Engine DJ database without allowing SQLite writes.

    ``Path.as_uri()`` supplies a platform-correct file URI and percent-encodes
    characters that would otherwise be interpreted as URI syntax. SQLite's
    ``mode=ro`` prevents a missing path from being created.
    """

    resolved = Path(db_path).expanduser().resolve()
    connection = sqlite3.connect(
        f"{resolved.as_uri()}?mode=ro",
        timeout=timeout,
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    return connection
