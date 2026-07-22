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
            "def backup_before_save():\n"
            "    create_verified_audio_backup()\n"
            "def write_audio_tags(tags):\n"
            "    backup_before_save()\n"
            "    tags.save()\n",
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


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        (
            "from sqlite3 import connect\ndef unsafe(path):\n    return connect(path)\n",
            "engine-db-direct-write",
        ),
        (
            "import sqlite3\ndef unsafe(path):\n"
            "    opener = sqlite3.connect\n    return opener(path)\n",
            "engine-db-direct-write",
        ),
        (
            "from engine_write_tags import write_audio_tags\ndef unsafe(path):\n"
            "    writer = write_audio_tags\n    return writer(path)\n",
            "audio-writer-bypass",
        ),
        (
            "def unsafe(tags):\n    persist = tags.save\n    persist()\n",
            "audio-save-without-approved-backup-writer",
        ),
        (
            "def unsafe(connection):\n    run = connection.execute\n"
            "    sql = \"DELETE FROM Track\"\n    run(sql)\n",
            "unapproved-persistent-sql",
        ),
        (
            "def unsafe(connection):\n"
            "    sql = \"UP\" + \"DATE Track SET genre = 'House'\"\n"
            "    connection.execute(sql)\n",
            "unapproved-persistent-sql",
        ),
        (
            "def unsafe(connection):\n"
            "    sql = \"UPDATE Track SET genre = '{}'\".format('House')\n"
            "    connection.execute(sql)\n",
            "unapproved-persistent-sql",
        ),
        (
            "def unsafe(connection):\n"
            "    sql = build_sql_at_runtime()\n"
            "    connection.execute(sql)\n",
            "unapproved-dynamic-sql",
        ),
    ],
)
def test_callable_alias_and_dynamic_sql_bypasses_are_detected(source, rule):
    assert rule in _rules(source, "tools/adversarial.py")


@pytest.mark.parametrize(
    "source",
    [
        (
            "def backup_before_save():\n"
            "    create_verified_audio_backup()\n"
            "def write_audio_tags(tags):\n"
            "    tags.save()\n"
            "    backup_before_save()\n"
        ),
        (
            "def backup_before_save():\n"
            "    create_verified_audio_backup()\n"
            "def write_audio_tags(tags, do_backup):\n"
            "    if do_backup:\n"
            "        backup_before_save()\n"
            "    else:\n"
            "        tags.save()\n"
        ),
        (
            "def write_audio_tags(tags):\n"
            "    def backup_before_save():\n"
            "        pass\n"
            "    backup_before_save()\n"
            "    tags.save()\n"
        ),
    ],
)
def test_backup_must_be_verified_and_dominate_each_save(source):
    assert "audio-backup-call-required" in _rules(
        source, "tools/engine_write_tags.py"
    )


@pytest.mark.parametrize(
    "source",
    [
        (
            "def update_genre():\n"
            "    safe_engine_db_write()\n"
            "    def never_called():\n"
            "        _submit_post_commit_audio_tags([])\n"
        ),
        (
            "def update_genre():\n"
            "    _submit_post_commit_audio_tags([])\n"
            "    safe_engine_db_write()\n"
        ),
        (
            "def update_genre():\n"
            "    safe_engine_db_write()\n"
            "    if False:\n"
            "        _submit_post_commit_audio_tags([])\n"
        ),
    ],
)
def test_post_commit_queue_must_be_reachable_and_after_safe_write(source):
    assert "post-commit-queue-required" in _rules(source)


@pytest.mark.parametrize(
    "source",
    [
        "def render(document):\n    document.save()\n",
        "def finish(repository):\n    repository.commit()\n",
        "def report(processor):\n    processor.execute('CREATE REPORT')\n",
        "import sqlite3\ndef temporary():\n    return sqlite3.connect(':memory:')\n",
    ],
)
def test_unrelated_common_method_names_are_not_persistent_write_violations(source):
    assert not analyze_sources([SourceFile("tools/report.py", source)])


def test_exact_allowlist_detects_disappearing_approved_call():
    sources = production_sources(REPO_ROOT)
    changed = []
    for item in sources:
        source = item.source
        if item.path == "tools/analysis_db.py":
            source = source.replace("connection.commit()", "connection.rollback()", 1)
        changed.append(SourceFile(item.path, source))
    assert "allowlist-exact-count-mismatch" in {
        violation.rule for violation in analyze_sources(changed)
    }


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        (
            "from sqlite3 import Connection\n"
            "def unsafe(path):\n    return Connection(path)\n",
            "engine-db-direct-write",
        ),
        (
            "import sqlite3\ndef unsafe(path):\n"
            "    return getattr(sqlite3, 'connect')(path)\n",
            "engine-db-direct-write",
        ),
        (
            "def unsafe(path):\n    return __import__('sqlite3').connect(path)\n",
            "engine-db-direct-write",
        ),
        (
            "def unsafe(cx):\n    cx.execute('DELETE FROM Track')\n",
            "unapproved-persistent-sql",
        ),
        (
            "from mutagen import File\ndef unsafe(path):\n"
            "    track_file = File(path)\n    track_file.save()\n",
            "audio-save-without-approved-backup-writer",
        ),
    ],
)
def test_equivalent_persistence_apis_and_opaque_receiver_names_are_detected(
    source, rule
):
    assert rule in _rules(source, "tools/adversarial.py")


@pytest.mark.parametrize(
    "source",
    [
        "def unsafe(connection):\n"
        "    connection.executescript('DELETE FROM Track;')\n",
        "def unsafe(connection):\n"
        "    connection.execute('-- generated\\nDELETE FROM Track')\n",
        "def unsafe(connection):\n"
        "    connection.execute('WITH ids AS (SELECT 1) DELETE FROM Track')\n",
        "def unsafe(connection):\n"
        "    connection.execute('PRAGMA user_version = 2')\n",
    ],
)
def test_additional_sql_mutations_are_detected(source):
    assert "unapproved-persistent-sql" in _rules(source, "tools/adversarial.py")


def test_unreachable_verified_backup_does_not_authorize_save():
    source = (
        "def backup_before_save():\n"
        "    if False:\n        create_verified_audio_backup()\n"
        "def write_audio_tags(tags):\n"
        "    backup_before_save()\n    tags.save()\n"
    )
    assert "audio-backup-call-required" in _rules(
        source, "tools/engine_write_tags.py"
    )


def test_conditionally_verified_backup_helper_does_not_authorize_save():
    source = (
        "def backup_before_save(required):\n"
        "    if required:\n        create_verified_audio_backup()\n"
        "def write_audio_tags(tags):\n"
        "    backup_before_save(False)\n    tags.save()\n"
    )
    assert "audio-backup-call-required" in _rules(
        source, "tools/engine_write_tags.py"
    )


def test_noop_callback_does_not_authorize_callback_writer_save():
    source = (
        "def _set_tags_mp3(tags, before_save=None):\n"
        "    if before_save is None:\n        raise RuntimeError\n"
        "    before_save()\n    tags.save()\n"
        "def main(tags):\n"
        "    _set_tags_mp3(tags, before_save=lambda: None)\n"
    )
    assert "audio-backup-callback-required" in _rules(
        source, "tools/engine_write_tags.py"
    )


def test_caught_safe_write_failure_cannot_reach_post_commit_queue():
    source = (
        "def update_genre():\n"
        "    try:\n        safe_engine_db_write()\n"
        "    except Exception:\n        pass\n"
        "    _submit_post_commit_audio_tags([])\n"
    )
    assert "post-commit-queue-required" in _rules(source)


def test_exact_allowlist_detects_changed_sql_operation():
    changed = []
    for item in production_sources(REPO_ROOT):
        source = item.source
        if item.path == "set_app/set_app.py":
            source = source.replace(
                "UPDATE Track SET lastEditTime = ? WHERE id = ?",
                "DELETE FROM Track WHERE id = ?",
                1,
            )
        changed.append(SourceFile(item.path, source))
    assert "allowlist-operation-mismatch" in {
        violation.rule for violation in analyze_sources(changed)
    }


def test_exact_allowlist_detects_disappearing_safe_write_call():
    changed = []
    for item in production_sources(REPO_ROOT):
        source = item.source
        if item.path == "set_app/set_app.py":
            source = source.replace("safe_engine_db_write(", "removed_safe_write(", 1)
        changed.append(SourceFile(item.path, source))
    assert "allowlist-safe-write-mismatch" in {
        violation.rule for violation in analyze_sources(changed)
    }


def test_function_parameter_shadowing_import_is_not_a_sqlite_call():
    source = (
        "from sqlite3 import connect\n"
        "def report(connect):\n    return connect('not sqlite')\n"
    )
    assert not analyze_sources([SourceFile("tools/report.py", source)])


@pytest.mark.parametrize(
    "source",
    [
        "import sqlite3\ndef unsafe(path):\n"
        "    return sqlite3.connect.__call__(path)\n",
        "from functools import partial\nimport sqlite3\ndef unsafe(path):\n"
        "    return partial(sqlite3.connect, path)()\n",
        "import sqlite3\ndef unsafe(path):\n"
        "    return vars(sqlite3)['connect'](path)\n",
    ],
)
def test_equivalent_sqlite_opener_invocations_are_detected(source):
    assert "engine-db-direct-write" in _rules(source, "tools/adversarial.py")


@pytest.mark.parametrize(
    "source",
    [
        "def unsafe(connection):\n"
        "    connection.execute('CREATE VIRTUAL TABLE secrets USING fts5(body)')\n",
        "def unsafe(connection):\n"
        "    connection.execute('PRAGMA schema_version = 999')\n",
    ],
)
def test_virtual_schema_and_writable_pragma_are_detected(source):
    assert "unapproved-persistent-sql" in _rules(source, "tools/adversarial.py")


@pytest.mark.parametrize(
    "source",
    [
        (
            "def backup_before_save(skip=True):\n"
            "    if skip:\n        return\n"
            "    create_verified_audio_backup()\n"
            "def write_audio_tags(tags):\n"
            "    backup_before_save()\n    tags.save()\n"
        ),
        (
            "def backup_before_save():\n"
            "    callback = lambda: create_verified_audio_backup()\n"
            "def write_audio_tags(tags):\n"
            "    backup_before_save()\n    tags.save()\n"
        ),
    ],
)
def test_early_return_and_uninvoked_lambda_do_not_authorize_backup(source):
    assert "audio-backup-call-required" in _rules(
        source, "tools/engine_write_tags.py"
    )


def test_local_safe_write_lookalike_is_rejected():
    source = (
        "def safe_engine_db_write(*args, **kwargs):\n    return None, None\n"
        "def update_genre():\n"
        "    safe_engine_db_write(None, None, 'update_track_genre', write_genre)\n"
        "    _submit_post_commit_audio_tags([])\n"
    )
    assert "engine-db-safe-write-origin" in _rules(source)


def test_conditional_safe_write_does_not_authorize_unconditional_queue():
    source = (
        "from engine_db_write import safe_engine_db_write\n"
        "def update_genre(do_write=False):\n"
        "    if do_write:\n"
        "        safe_engine_db_write(None, None, 'update_track_genre', write_genre)\n"
        "    _submit_post_commit_audio_tags([])\n"
    )
    violations = analyze_sources([SourceFile("set_app/set_app.py", source)])
    assert any(
        item.rule == "post-commit-queue-required" and item.call == "update_genre"
        for item in violations
    )


def test_exact_allowlist_detects_changed_sql_with_same_operation_and_table():
    changed = []
    for item in production_sources(REPO_ROOT):
        source = item.source
        if item.path == "set_app/set_app.py":
            source = source.replace(
                "UPDATE Track SET lastEditTime = ? WHERE id = ?",
                "UPDATE Track SET rating = 0 WHERE id = ?",
                1,
            )
        changed.append(SourceFile(item.path, source))
    assert "allowlist-sql-fingerprint-mismatch" in {
        violation.rule for violation in analyze_sources(changed)
    }
