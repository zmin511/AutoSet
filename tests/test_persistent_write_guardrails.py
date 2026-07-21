from pathlib import Path

import pytest

from persistent_write_guardrail import (
    SourceFile,
    analyze_sources,
    format_violations,
    production_sources,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _rules(source: str, path: str = "set_app/set_app.py") -> set[str]:
    return {item.rule for item in analyze_sources([SourceFile(path, source)])}


def test_production_persistent_writes_match_architecture_policy():
    violations = analyze_sources(production_sources(REPO_ROOT))
    assert not violations, format_violations(violations)


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        (
            "import sqlite3\ndef save(db_path):\n    return sqlite3.connect(db_path)\n",
            "engine-db-direct-write",
        ),
        (
            "import sqlite3 as sql\ndef load():\n"
            "    return sql.connect('file:m.db?mode=ro', uri=True)\n",
            "engine-db-direct-read",
        ),
        (
            "def unsafe(connection):\n"
            "    connection.execute('UPDATE Track SET genre = ?', ('House',))\n",
            "unapproved-persistent-sql",
        ),
        (
            "def unsafe(connection):\n    connection.commit()\n",
            "unapproved-persistent-commit",
        ),
        (
            "def unsafe(tags):\n    tags.save()\n",
            "audio-save-without-approved-backup-writer",
        ),
        (
            "def write_audio_tags(tags):\n    tags.save()\n",
            "audio-backup-call-required",
        ),
        (
            "from engine_write_tags import write_audio_tags\n"
            "def update_genre():\n    write_audio_tags('song.mp3')\n",
            "audio-writer-bypass",
        ),
        (
            "def refresh_tags(): pass\ndef main():\n    refresh_tags()\n",
            "startup-persistent-audio-write",
        ),
        (
            "def retry_pending_audio_tags(): pass\n"
            "def startup_retry():\n    retry_pending_audio_tags()\n"
            "def main():\n    startup_retry()\n",
            "startup-persistent-audio-write",
        ),
        (
            "import threading\n"
            "from audio_tag_post_commit import retry_pending_audio_tags as retry_now\n"
            "def main():\n    threading.Thread(target=retry_now).start()\n",
            "startup-background-audio-write",
        ),
    ],
)
def test_unsafe_fixture_is_detected(tmp_path, source, rule):
    fixture = tmp_path / "unsafe.py"
    fixture.write_text(source, encoding="utf-8")
    path = (
        "tools/engine_write_tags.py"
        if rule == "audio-backup-call-required"
        else "set_app/set_app.py"
    )
    rules = _rules(fixture.read_text(encoding="utf-8"), path)
    assert rule in rules


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (
            "tools/analysis_db.py",
            "import sqlite3\ndef open_analysis_db(path):\n    return sqlite3.connect(path)\n",
        ),
        (
            "tools/audio_tag_post_commit.py",
            "import sqlite3\ndef _connect(path):\n    return sqlite3.connect(path)\n",
        ),
        (
            "tools/engine_db_read.py",
            "import sqlite3\ndef open_engine_db_read_only(uri):\n"
            "    return sqlite3.connect(uri, uri=True)\n",
        ),
        (
            "tools/engine_db_write.py",
            "import sqlite3\ndef safe_engine_db_write(uri):\n"
            "    return sqlite3.connect(uri, uri=True)\n",
        ),
        (
            "tools/engine_write_tags.py",
            "def write_audio_tags(tags):\n    backup_before_save()\n    tags.save()\n",
        ),
    ],
)
def test_approved_fixture_is_not_blocked(tmp_path, path, source):
    fixture = tmp_path / Path(path).name
    fixture.write_text(source, encoding="utf-8")
    assert not analyze_sources([SourceFile(path, fixture.read_text(encoding="utf-8"))])


def test_approved_engine_read_only_opener_call_is_not_blocked():
    source = (
        "from engine_db_read import open_engine_db_read_only as open_ro\n"
        "def load(path):\n    return open_ro(path)\n"
    )
    assert not analyze_sources([SourceFile("tools/report.py", source)])


def test_violation_message_has_actionable_location_and_remediation():
    violations = analyze_sources(
        [SourceFile("set_app/bad.py", "def save(tags):\n    tags.save()\n")]
    )
    message = format_violations(violations)
    assert "set_app/bad.py:2" in message
    assert "tags.save()" in message
    assert "audio-save-without-approved-backup-writer" in message
    assert "Use write_audio_tags()" in message
