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
        (
            "def verified():\n    create_verified_audio_backup()\n"
            "def noop():\n    pass\n"
            "def write_audio_tags(tags):\n"
            "    for backup_before_save in [verified, noop]:\n"
            "        backup_before_save()\n"
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


def test_imported_safe_write_shadowed_by_function_is_rejected():
    source = (
        "from engine_db_write import safe_engine_db_write\n"
        "def safe_engine_db_write(*args, **kwargs):\n    return None, None\n"
        "def update_genre():\n"
        "    safe_engine_db_write(None, None, 'update_track_genre', write_genre)\n"
        "    _submit_post_commit_audio_tags([])\n"
    )
    assert "engine-db-safe-write-origin" in _rules(source)


def test_nested_backup_name_resolves_in_lexical_scope():
    source = (
        "def backup_before_save():\n    create_verified_audio_backup()\n"
        "def write_audio_tags(tags):\n"
        "    def backup_before_save():\n        pass\n"
        "    backup_before_save()\n"
        "    tags.save()\n"
    )
    assert "audio-backup-call-required" in _rules(
        source, "tools/engine_write_tags.py"
    )


def test_sqlite_opener_in_parameter_default_is_detected():
    source = (
        "import sqlite3\n"
        "def unsafe(path, opener=sqlite3.connect):\n    return opener(path)\n"
    )
    assert "engine-db-direct-write" in _rules(source, "tools/adversarial.py")


def test_operator_methodcaller_sql_mutation_is_detected():
    source = (
        "from operator import methodcaller\n"
        "def unsafe(connection):\n"
        "    methodcaller('execute', 'DELETE FROM Track')(connection)\n"
    )
    assert "unapproved-persistent-sql" in _rules(source, "tools/adversarial.py")


def test_function_style_writable_pragma_is_detected():
    source = (
        "def unsafe(connection):\n"
        "    connection.execute('PRAGMA user_version(999)')\n"
    )
    assert "unapproved-persistent-sql" in _rules(source, "tools/adversarial.py")


def test_unknown_save_receiver_is_denied_by_default():
    source = "def unsafe(track_file):\n    track_file.save()\n"
    assert "audio-save-without-approved-backup-writer" in _rules(
        source, "tools/helper.py"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "PRAGMA table_info(Track)",
        "PRAGMA integrity_check",
        "PRAGMA foreign_keys",
    ],
)
def test_reviewed_read_only_pragma_forms_are_not_mutations(sql):
    source = f"def inspect(connection):\n    connection.execute({sql!r})\n"
    assert "unapproved-persistent-sql" not in _rules(source, "tools/report.py")


@pytest.mark.parametrize(
    "source",
    [
        (
            "import sqlite3\n"
            "def unsafe(path):\n"
            "    for opener in [sqlite3.connect]:\n"
            "        return opener(path)\n"
        ),
        (
            "import sqlite3\n"
            "def unsafe(path):\n"
            "    for opener in [print, sqlite3.connect]:\n"
            "        opener(path)\n"
        ),
        (
            "import sqlite3\n"
            "def unsafe(paths):\n"
            "    return [opener(path) for opener in [sqlite3.connect] "
            "for path in paths]\n"
        ),
        "import sqlite3\nopener, = (sqlite3.connect,)\nopener('unsafe.db')\n",
        (
            "import sqlite3\n"
            "unsafe = lambda path, opener=sqlite3.connect: opener(path)\n"
        ),
        "import sqlite3\nsqlite3.dbapi2.connect('unsafe.db')\n",
        "import sqlite3\n{'open': sqlite3.connect}['open']('unsafe.db')\n",
        (
            "import sqlite3\n"
            "openers = {'open': sqlite3.connect}\n"
            "openers['open']('unsafe.db')\n"
        ),
        (
            "import sqlite3\n"
            "getattr(sqlite3, 'con' + 'nect')('unsafe.db')\n"
        ),
        (
            "import sqlite3\n"
            "def unsafe(path, enabled):\n"
            "    opener = sqlite3.connect if enabled else print\n"
            "    opener(path)\n"
        ),
    ],
)
def test_container_loop_unpack_lambda_and_computed_sqlite_openers_are_detected(source):
    assert "engine-db-direct-write" in _rules(source, "tools/adversarial.py")


@pytest.mark.parametrize(
    "source",
    [
        (
            "def unsafe(connection):\n"
            "    for run in [connection.execute]:\n"
            "        run('DELETE FROM Track')\n"
        ),
        (
            "def unsafe(connection):\n"
            "    for run in [print, connection.execute]:\n"
            "        run('DELETE FROM Track')\n"
        ),
        (
            "def unsafe(connection):\n"
            "    getattr(connection, 'ex' + 'ecute')('DELETE FROM Track')\n"
        ),
        (
            "import operator\n"
            "def unsafe(connection):\n"
            "    operator.methodcaller(\n"
            "        'ex' + 'ecute', 'DELETE FROM Track'\n"
            "    )(connection)\n"
        ),
        (
            "def unsafe(connection, key):\n"
            "    runners = {'read': print, 'write': connection.execute}\n"
            "    runners[key]('DELETE FROM Track')\n"
        ),
    ],
)
def test_aliased_and_computed_sql_invocations_are_detected(source):
    assert "unapproved-persistent-sql" in _rules(source, "tools/adversarial.py")


@pytest.mark.parametrize(
    "source",
    [
        (
            "def unsafe(tags):\n"
            "    for persist in [tags.save]:\n"
            "        persist()\n"
        ),
        (
            "def unsafe(tags):\n"
            "    for persist in [print, tags.save]:\n"
            "        persist()\n"
        ),
        "def unsafe(tags):\n    getattr(tags, 'sa' + 've')()\n",
        (
            "def unsafe(tags, enabled):\n"
            "    persist = tags.save if enabled else print\n"
            "    persist()\n"
        ),
    ],
)
def test_aliased_and_computed_audio_saves_are_detected(source):
    assert "audio-save-without-approved-backup-writer" in _rules(
        source, "tools/adversarial.py"
    )


def test_nested_post_commit_helper_lookalike_is_rejected():
    source = (
        "from engine_db_write import safe_engine_db_write\n"
        "def update_genre():\n"
        "    def _submit_post_commit_audio_tags(_jobs):\n"
        "        return None, []\n"
        "    safe_engine_db_write(None, None, 'update_track_genre', write_genre)\n"
        "    _submit_post_commit_audio_tags([])\n"
    )
    assert "post-commit-queue-required" in _rules(source)


def test_nested_durable_queue_submitter_lookalike_is_rejected():
    source = (
        "def _submit_post_commit_audio_tags(jobs):\n"
        "    def submit_audio_tag_jobs(_jobs):\n"
        "        return None, []\n"
        "    return submit_audio_tag_jobs(jobs)\n"
    )
    assert "post-commit-queue-required" in _rules(source)


def test_aliased_internal_audio_writer_requires_verified_backup_callback():
    source = (
        "from engine_write_tags import _set_tags_mp3\n"
        "def unsafe(path):\n"
        "    for writer in [_set_tags_mp3]:\n"
        "        writer(path, '128', '8A', True, before_save=lambda: None)\n"
    )
    assert "audio-backup-callback-required" in _rules(
        source, "tools/adversarial.py"
    )


def test_imports_are_resolved_in_their_lexical_scope():
    source = (
        "import sqlite3\n"
        "def unsafe(path):\n"
        "    return sqlite3.connect(path)\n"
        "def unrelated():\n"
        "    import json as sqlite3\n"
        "    return sqlite3.dumps({})\n"
    )
    assert "engine-db-direct-write" in _rules(source, "tools/adversarial.py")


@pytest.mark.parametrize(
    "source",
    [
        (
            "import sqlite3\n"
            "def unsafe(path):\n"
            "    return getattr(sqlite3, ''.join(('con', 'nect')))(path)\n"
        ),
        (
            "import sqlite3\n"
            "def unsafe(path):\n"
            "    return vars(sqlite3).get('connect')(path)\n"
        ),
        (
            "import operator, sqlite3\n"
            "def unsafe(path):\n"
            "    return operator.attrgetter('connect')(sqlite3)(path)\n"
        ),
        (
            "def unsafe(connection, name):\n"
            "    return getattr(connection, name)('DELETE FROM Track')\n"
        ),
        (
            "def unsafe(connection):\n"
            "    return object.__getattribute__(connection, 'execute')"
            "('DELETE FROM Track')\n"
        ),
        (
            "def unsafe(connection):\n"
            "    return type(connection).__dict__['execute']"
            "(connection, 'DELETE FROM Track')\n"
        ),
        (
            "import sqlite3\n"
            "def unsafe(path):\n"
            "    opener = sqlite3.__dict__.get('connect')\n"
            "    return opener(path)\n"
        ),
    ],
)
def test_reflective_callable_construction_is_fail_closed(source):
    rules = _rules(source, "tools/adversarial.py")
    assert rules & {
        "dynamic-persistence-capability",
        "unreviewed-dynamic-getattr",
        "unreviewed-reflective-call",
        "unreviewed-reflective-attribute",
    }


@pytest.mark.parametrize(
    "source",
    [
        (
            "from functools import partial\n"
            "def unsafe(connection):\n"
            "    partial(connection.execute, 'DELETE FROM Track')()\n"
        ),
        (
            "def unsafe(connection):\n"
            "    list(map(connection.execute, ['DELETE FROM Track']))\n"
        ),
        (
            "from functools import partial\n"
            "def unsafe(tags):\n"
            "    partial(tags.save)()\n"
        ),
        (
            "def unsafe(tags):\n"
            "    list(map(lambda callback: callback(), [tags.save]))\n"
        ),
        (
            "import sqlite3\n"
            "callbacks = [sqlite3.connect]\n"
        ),
        (
            "def unsafe(connection, tags):\n"
            "    callbacks = [connection.execute, tags.save]\n"
            "    return callbacks\n"
        ),
    ],
)
def test_persistence_callables_cannot_be_transferred_as_values(source):
    assert "persistent-callable-transfer" in _rules(
        source, "tools/adversarial.py"
    )


def test_wildcard_import_cannot_hide_sqlite_opener_origin():
    source = "from sqlite3 import *\ndef unsafe(path):\n    return connect(path)\n"
    assert "unreviewed-wildcard-import" in _rules(
        source, "tools/adversarial.py"
    )
