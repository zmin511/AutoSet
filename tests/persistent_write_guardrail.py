"""AST checks that keep persistent writes behind AutoSet's safety boundaries."""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


PRODUCTION_ROOTS = ("set_app", "tools")

# Every exception is a precise (repository path, containing symbol) pair.  Counts
# make adding another call inside an already-approved symbol an explicit policy
# change as well.
SQLITE_CONNECT_ALLOWLIST = {
    ("set_app/set_app.py", "analysis_database_status"): (
        1,
        "read-only inspection of AutoSet's separate analysis.db",
    ),
    ("tools/analysis_db.py", "open_analysis_db"): (
        1,
        "the dedicated analysis.db connection factory",
    ),
    ("tools/audio_tag_post_commit.py", "_connect"): (
        1,
        "the durable audio-tag retry queue connection factory",
    ),
    ("tools/engine_db_read.py", "open_engine_db_read_only"): (
        1,
        "the shared Engine DB read-only opener implementation",
    ),
    ("tools/engine_db_write.py", "_create_verified_backup"): (
        3,
        "read source, write backup, and verify backup inside safe Engine DB write",
    ),
    ("tools/engine_db_write.py", "safe_engine_db_write"): (
        1,
        "the single writable Engine DB connection, opened only after lock acquisition",
    ),
}

SAFE_ENGINE_WRITE_CALLS = {
    ("set_app/set_app.py", "export_track_marks_to_engine"),
    ("set_app/set_app.py", "update_genre"),
    ("set_app/set_app.py", "detail_folder_styles"),
    ("set_app/set_app.py", "bulk_update_genres"),
    ("set_app/set_app.py", "create_engine_playlist_from_tracks"),
    ("set_app/set_app.py", "_write_energy_ratings_for_paths"),
}

SQL_MUTATION_ALLOWLIST = {
    ("set_app/set_app.py", "export_track_marks_to_engine.write_export"): (
        2,
        "Engine cue/loop mutation inside an approved safe-write callback",
    ),
    ("set_app/set_app.py", "update_genre.write_genre"): (
        1,
        "Engine genre mutation inside an approved safe-write callback",
    ),
    ("set_app/set_app.py", "detail_folder_styles.write_detail_styles"): (
        1,
        "Engine style mutation inside an approved safe-write callback",
    ),
    ("set_app/set_app.py", "bulk_update_genres.write_bulk_genres"): (
        1,
        "Engine bulk-genre mutation inside an approved safe-write callback",
    ),
    ("set_app/set_app.py", "_insert_playlist"): (
        2,
        "playlist helper used only by the approved playlist safe-write callback",
    ),
    ("set_app/set_app.py", "create_engine_playlist_from_tracks.write_playlist"): (
        4,
        "Engine playlist mutation inside an approved safe-write callback",
    ),
    (
        "set_app/set_app.py",
        "_write_energy_ratings_for_paths.write_energy_ratings_batch",
    ): (1, "Engine rating mutation inside an approved safe-write callback"),
    ("tools/analysis_db.py", "upsert_profile"): (
        1,
        "write to AutoSet's separate analysis.db",
    ),
    ("tools/analysis_db.py", "delete_profile_by_path"): (
        1,
        "delete from AutoSet's separate analysis.db",
    ),
    ("tools/audio_tag_post_commit.py", "_create_indexes"): (
        3,
        "retry-queue schema indexes",
    ),
    ("tools/audio_tag_post_commit.py", "_migrate_or_create_schema"): (
        5,
        "retry-queue transaction and schema migration",
    ),
    ("tools/audio_tag_post_commit.py", "enqueue_audio_tag_jobs"): (
        3,
        "durable retry-queue enqueue transaction",
    ),
    ("tools/audio_tag_post_commit.py", "_claim_job"): (
        3,
        "retry-queue lease recovery and atomic claim",
    ),
    ("tools/audio_tag_post_commit.py", "_complete_claim"): (
        1,
        "retry-queue owner-token completion",
    ),
    ("tools/engine_db_write.py", "safe_engine_db_write"): (
        1,
        "transaction start inside the approved Engine DB safe writer",
    ),
}

COMMIT_ALLOWLIST = {
    ("tools/analysis_db.py", "initialize_schema"): (
        1,
        "analysis.db schema transaction",
    ),
    ("tools/analysis_db.py", "upsert_profile"): (1, "analysis.db profile write"),
    ("tools/analysis_db.py", "delete_profile_by_path"): (
        1,
        "analysis.db profile deletion",
    ),
    ("tools/audio_tag_post_commit.py", "_migrate_or_create_schema"): (
        3,
        "retry-queue schema creation/migration",
    ),
    ("tools/audio_tag_post_commit.py", "enqueue_audio_tag_jobs"): (
        1,
        "retry-queue enqueue transaction",
    ),
    ("tools/audio_tag_post_commit.py", "_claim_job"): (
        2,
        "retry-queue recovery/claim transaction",
    ),
    ("tools/audio_tag_post_commit.py", "_complete_claim"): (
        1,
        "retry-queue claim completion transaction",
    ),
    ("tools/engine_db_write.py", "_create_verified_backup"): (
        1,
        "verified Engine DB backup destination",
    ),
    ("tools/engine_db_write.py", "safe_engine_db_write"): (
        1,
        "the only Engine DB commit boundary",
    ),
}

AUDIO_SAVE_ALLOWLIST = {
    ("tools/engine_write_tags.py", "write_audio_tags"): (
        3,
        "MP3, FLAC, and MP4 saves after create_verified_audio_backup",
    ),
    ("tools/engine_write_tags.py", "_set_tags_mp3"): (
        1,
        "CLI MP3 save after the mandatory before_save callback",
    ),
    ("tools/engine_write_tags.py", "_set_bitrate_tag_mp3"): (
        1,
        "CLI MP3 bitrate save after the mandatory before_save callback",
    ),
    ("tools/engine_write_tags.py", "_set_tags_flac"): (
        1,
        "CLI FLAC save after the mandatory before_save callback",
    ),
    ("tools/engine_write_tags.py", "_set_bitrate_tag_flac"): (
        1,
        "CLI FLAC bitrate save after the mandatory before_save callback",
    ),
    ("tools/review_new_genres.py", "write_mp3_tags"): (
        1,
        "genre MP3 save after ensure_backup",
    ),
    ("tools/review_new_genres.py", "write_flac_tags"): (
        1,
        "genre FLAC save after ensure_backup",
    ),
}

AUDIO_BACKUP_CALLS = {
    ("tools/engine_write_tags.py", "write_audio_tags"): "backup_before_save",
    ("tools/engine_write_tags.py", "_set_tags_mp3"): "before_save",
    ("tools/engine_write_tags.py", "_set_bitrate_tag_mp3"): "before_save",
    ("tools/engine_write_tags.py", "_set_tags_flac"): "before_save",
    ("tools/engine_write_tags.py", "_set_bitrate_tag_flac"): "before_save",
    ("tools/review_new_genres.py", "write_mp3_tags"): "ensure_backup",
    ("tools/review_new_genres.py", "write_flac_tags"): "ensure_backup",
}

DIRECT_AUDIO_WRITER_ALLOWLIST = {
    ("set_app/set_app.py", "_track_file_tag_result", "write_audio_tags"),
    ("tools/audio_tag_post_commit.py", "_default_writer", "write_audio_tags"),
    ("tools/engine_write_tags.py", "main", "write_audio_tags"),
    ("tools/review_new_genres.py", "main", "write_tags"),
}

POST_COMMIT_QUEUE_CALLS = {
    "update_genre": "_submit_post_commit_audio_tags",
    "detail_folder_styles": "_submit_post_commit_audio_tags",
    "bulk_update_genres": "_submit_post_commit_audio_tags",
    "_write_energy_ratings_for_paths": "_submit_post_commit_audio_tags",
    "_submit_post_commit_audio_tags": "submit_audio_tag_jobs",
}

STARTUP_FORBIDDEN_CALLS = {
    "process_pending_audio_tag_jobs",
    "refresh_genres",
    "refresh_tags",
    "retry_pending_audio_tags",
    "submit_audio_tag_jobs",
    "write_audio_tags",
    "write_tags",
}

_MUTATING_SQL = re.compile(
    r"^(?:INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|REPLACE|BEGIN|VACUUM|ATTACH|DETACH)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Violation:
    rule: str
    path: str
    line: int
    call: str
    detail: str
    safe_mechanism: str

    def __str__(self) -> str:
        return (
            f"{self.path}:{self.line}: {self.rule}: found {self.call}; "
            f"{self.detail}. Use {self.safe_mechanism}."
        )


@dataclass(frozen=True)
class SourceFile:
    path: str
    source: str


class _SourceAnalysis:
    def __init__(self, item: SourceFile) -> None:
        self.item = item
        self.tree = ast.parse(item.source.lstrip("\ufeff"), filename=item.path)
        self.parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                self.parents[child] = node
        self.imports = self._imports()
        self.functions = {
            node.name: node
            for node in self.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _imports(self) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    aliases[name.asname or name.name.split(".")[0]] = name.name
            elif isinstance(node, ast.ImportFrom):
                for name in node.names:
                    aliases[name.asname or name.name] = name.name
        return aliases

    def symbol(self, node: ast.AST) -> str:
        scopes: list[str] = []
        current = node
        while current in self.parents:
            current = self.parents[current]
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scopes.append(current.name)
        return ".".join(reversed(scopes)) or "<module>"

    def expression_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return self.imports.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            base = self.expression_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        return ast.unparse(node)

    def call_name(self, node: ast.Call) -> str:
        return self.expression_name(node.func)

    def calls(self) -> list[ast.Call]:
        return [node for node in ast.walk(self.tree) if isinstance(node, ast.Call)]


def production_sources(repo_root: Path) -> list[SourceFile]:
    result = []
    for root in PRODUCTION_ROOTS:
        for path in sorted((repo_root / root).rglob("*.py")):
            result.append(
                SourceFile(
                    path.as_posix().removeprefix(repo_root.as_posix() + "/"),
                    path.read_text(encoding="utf-8-sig"),
                )
            )
    return result


def _last_name(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _is_read_only_connect(node: ast.Call) -> bool:
    rendered = " ".join(ast.unparse(arg) for arg in node.args)
    rendered += " " + " ".join(ast.unparse(item.value) for item in node.keywords)
    return "mode=ro" in rendered.replace(" ", "").casefold()


def _literal_sql(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return " ".join(node.value.split())
    if isinstance(node, ast.JoinedStr):
        text = "".join(
            value.value
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )
        return " ".join(text.split())
    return None


def _violation(
    rule: str,
    analysis: _SourceAnalysis,
    node: ast.AST,
    call: str,
    detail: str,
    safe_mechanism: str,
) -> Violation:
    return Violation(
        rule,
        analysis.item.path,
        getattr(node, "lineno", 1),
        call,
        detail,
        safe_mechanism,
    )


def _check_calls(analysis: _SourceAnalysis) -> list[Violation]:
    violations: list[Violation] = []
    connect_counts: Counter[tuple[str, str]] = Counter()
    commit_counts: Counter[tuple[str, str]] = Counter()
    mutation_counts: Counter[tuple[str, str]] = Counter()
    save_counts: Counter[tuple[str, str]] = Counter()
    first_save: dict[tuple[str, str], ast.Call] = {}

    for call in analysis.calls():
        full_name = analysis.call_name(call)
        name = _last_name(full_name)
        symbol = analysis.symbol(call)
        key = (analysis.item.path, symbol)

        if full_name == "sqlite3.connect":
            connect_counts[key] += 1
            allowed = SQLITE_CONNECT_ALLOWLIST.get(key)
            if allowed is None or connect_counts[key] > allowed[0]:
                read_only = _is_read_only_connect(call)
                violations.append(
                    _violation(
                        "engine-db-direct-read" if read_only else "engine-db-direct-write",
                        analysis,
                        call,
                        ast.unparse(call),
                        "unapproved direct SQLite connection in production code",
                        (
                            "open_engine_db_read_only()"
                            if read_only
                            else "safe_engine_db_write() (or a documented non-Engine DB factory)"
                        ),
                    )
                )

        if name == "safe_engine_db_write" and key not in SAFE_ENGINE_WRITE_CALLS:
            violations.append(
                _violation(
                    "engine-db-new-write-entrypoint",
                    analysis,
                    call,
                    ast.unparse(call),
                    "the Engine DB write entrypoint is not in the minimal allowlist",
                    "an architecture review and an exact SAFE_ENGINE_WRITE_CALLS entry",
                )
            )

        if name == "commit":
            commit_counts[key] += 1
            allowed = COMMIT_ALLOWLIST.get(key)
            if allowed is None or commit_counts[key] > allowed[0]:
                violations.append(
                    _violation(
                        "unapproved-persistent-commit",
                        analysis,
                        call,
                        ast.unparse(call),
                        "commit is outside an exact reviewed transaction boundary",
                        "safe_engine_db_write() or a documented non-Engine DB factory",
                    )
                )

        if name in {"execute", "executemany"} and call.args:
            sql = _literal_sql(call.args[0])
            if sql and _MUTATING_SQL.match(sql):
                mutation_counts[key] += 1
                allowed = SQL_MUTATION_ALLOWLIST.get(key)
                if allowed is None or mutation_counts[key] > allowed[0]:
                    violations.append(
                        _violation(
                            "unapproved-persistent-sql",
                            analysis,
                            call,
                            f"{name}({sql[:80]!r})",
                            "mutating SQL is outside an exact reviewed persistence symbol",
                            "a safe Engine callback or documented analysis/queue storage function",
                        )
                    )

        if name == "save":
            save_counts[key] += 1
            first_save.setdefault(key, call)
            allowed = AUDIO_SAVE_ALLOWLIST.get(key)
            if allowed is None or save_counts[key] > allowed[0]:
                violations.append(
                    _violation(
                        "audio-save-without-approved-backup-writer",
                        analysis,
                        call,
                        ast.unparse(call),
                        "metadata is saved outside a reviewed backup-enforcing writer",
                        "write_audio_tags() or a documented writer that verifies backup first",
                    )
                )

        if name in {"write_audio_tags", "write_tags"}:
            writer_key = (analysis.item.path, symbol, name)
            if writer_key not in DIRECT_AUDIO_WRITER_ALLOWLIST:
                violations.append(
                    _violation(
                        "audio-writer-bypass",
                        analysis,
                        call,
                        ast.unparse(call),
                        "direct audio-tag writer call is not an approved manual or queue writer",
                        "submit_audio_tag_jobs() for post-commit work",
                    )
                )

    for key, save_count in save_counts.items():
        required_call = AUDIO_BACKUP_CALLS.get(key)
        if required_call is None:
            continue
        function = analysis.functions.get(key[1])
        backup_count = (
            sum(
                _last_name(analysis.call_name(call)) == required_call
                for call in ast.walk(function)
                if isinstance(call, ast.Call)
            )
            if function is not None
            else 0
        )
        if backup_count < save_count:
            violations.append(
                _violation(
                    "audio-backup-call-required",
                    analysis,
                    first_save[key],
                    f"{key[1]}: {save_count} save call(s), {backup_count} backup call(s)",
                    "an approved audio writer no longer backs up every save path",
                    f"{required_call}() before each metadata save",
                )
            )

    return violations


def _function_call_names(analysis: _SourceAnalysis, node: ast.AST) -> set[str]:
    return {
        _last_name(analysis.call_name(call))
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
    }


def _check_post_commit(analysis: _SourceAnalysis) -> list[Violation]:
    if analysis.item.path != "set_app/set_app.py":
        return []
    violations = []
    for function, required_call in POST_COMMIT_QUEUE_CALLS.items():
        node = analysis.functions.get(function)
        if node is None or required_call not in _function_call_names(analysis, node):
            violations.append(
                _violation(
                    "post-commit-queue-required",
                    analysis,
                    node or analysis.tree,
                    function,
                    f"required call {required_call} is missing",
                    "submit_audio_tag_jobs() and the durable SQLite retry queue",
                )
            )
    return violations


def _startup_reachable_functions(analysis: _SourceAnalysis) -> set[str]:
    reachable: set[str] = set()
    pending = ["main"]
    while pending:
        name = pending.pop()
        if name in reachable or name not in analysis.functions:
            continue
        reachable.add(name)
        node = analysis.functions[name]
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            called = _last_name(analysis.call_name(call))
            if called in analysis.functions:
                pending.append(called)
            for keyword in call.keywords:
                if keyword.arg == "target" and isinstance(keyword.value, ast.Name):
                    target = _last_name(analysis.expression_name(keyword.value))
                    if target in analysis.functions:
                        pending.append(target)
    return reachable


def _check_startup(analysis: _SourceAnalysis) -> list[Violation]:
    if analysis.item.path != "set_app/set_app.py" or "main" not in analysis.functions:
        return []
    violations = []
    for function in _startup_reachable_functions(analysis):
        node = analysis.functions[function]
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                name = _last_name(analysis.call_name(child))
                if name in STARTUP_FORBIDDEN_CALLS:
                    violations.append(
                        _violation(
                            "startup-persistent-audio-write",
                            analysis,
                            child,
                            ast.unparse(child),
                            f"{function} is reachable from application startup",
                            "an explicit manual API action; startup may only update analysis.db",
                        )
                    )
                for keyword in child.keywords:
                    if keyword.arg != "target":
                        continue
                    target = _last_name(analysis.expression_name(keyword.value))
                    if target in STARTUP_FORBIDDEN_CALLS:
                        violations.append(
                            _violation(
                                "startup-background-audio-write",
                                analysis,
                                child,
                                ast.unparse(child),
                                f"background target {target} may modify audio or retry state",
                                "a manual endpoint instead of a startup thread/task/process",
                            )
                        )
    return violations


def analyze_sources(items: list[SourceFile]) -> list[Violation]:
    violations = []
    for item in items:
        analysis = _SourceAnalysis(item)
        violations.extend(_check_calls(analysis))
        violations.extend(_check_post_commit(analysis))
        violations.extend(_check_startup(analysis))
    return sorted(violations, key=lambda item: (item.path, item.line, item.rule))


def format_violations(violations: list[Violation]) -> str:
    return "\n".join(str(item) for item in violations)
