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
        7,
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
    r"^(?:INSERT|UPDATE|DELETE|REPLACE|BEGIN|VACUUM|ATTACH|DETACH|"
    r"CREATE\s+(?:TABLE|INDEX|TRIGGER|VIEW)|"
    r"DROP\s+(?:TABLE|INDEX|TRIGGER|VIEW)|"
    r"ALTER\s+TABLE)\b",
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
        self.bindings = self._bindings()
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
                    qualified = f"{node.module}.{name.name}" if node.module else name.name
                    aliases[name.asname or name.name] = qualified
        return aliases

    def _bindings(self) -> dict[tuple[str, str], list[tuple[int, ast.AST]]]:
        bindings: dict[tuple[str, str], list[tuple[int, ast.AST]]] = {}
        for node in ast.walk(self.tree):
            value: ast.AST | None = None
            targets: list[ast.AST] = []
            if isinstance(node, ast.Assign):
                value, targets = node.value, node.targets
            elif isinstance(node, ast.AnnAssign):
                value, targets = node.value, [node.target]
            elif isinstance(node, ast.NamedExpr):
                value, targets = node.value, [node.target]
            if value is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings.setdefault((self.symbol(node), target.id), []).append(
                        (node.lineno, value)
                    )
        return bindings

    def _binding(self, name: str, context: ast.AST) -> ast.AST | None:
        """Return the latest simple assignment visible before *context*."""
        line = getattr(context, "lineno", 10**9)
        symbol = self.symbol(context)
        candidates = [
            item
            for scope in (symbol, "<module>")
            for item in self.bindings.get((scope, name), [])
            if item[0] < line
        ]
        return max(candidates, default=(0, None), key=lambda item: item[0])[1]

    def symbol(self, node: ast.AST) -> str:
        scopes: list[str] = []
        current = node
        while current in self.parents:
            current = self.parents[current]
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scopes.append(current.name)
        return ".".join(reversed(scopes)) or "<module>"

    def expression_name(
        self,
        node: ast.AST,
        context: ast.AST | None = None,
        seen: frozenset[str] = frozenset(),
    ) -> str:
        context = context or node
        if isinstance(node, ast.Name):
            if node.id in self.imports:
                return self.imports[node.id]
            if node.id not in seen:
                binding = self._binding(node.id, context)
                if binding is not None:
                    return self.expression_name(binding, context, seen | {node.id})
            return node.id
        if isinstance(node, ast.Attribute):
            base = self.expression_name(node.value, context, seen)
            return f"{base}.{node.attr}" if base else node.attr
        return ast.unparse(node)

    def call_name(self, node: ast.Call) -> str:
        return self.expression_name(node.func, node)

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


def _is_memory_connect(node: ast.Call) -> bool:
    return bool(
        node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == ":memory:"
    )


def _static_string(
    analysis: _SourceAnalysis,
    node: ast.AST,
    context: ast.AST,
    seen: frozenset[str] = frozenset(),
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id not in seen:
        binding = analysis._binding(node.id, context)
        if binding is not None:
            return _static_string(analysis, binding, context, seen | {node.id})
    if isinstance(node, ast.JoinedStr):
        return "".join(
            value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else "?"
            for value in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        left = _static_string(analysis, node.left, context, seen)
        right = _static_string(analysis, node.right, context, seen)
        if isinstance(node.op, ast.Add) and left is not None and right is not None:
            return left + right
        if isinstance(node.op, ast.Mod) and left is not None:
            return left
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    ):
        return _static_string(analysis, node.func.value, context, seen)
    return None


def _literal_sql(analysis: _SourceAnalysis, node: ast.AST, context: ast.AST) -> str | None:
    value = _static_string(analysis, node, context)
    return " ".join(value.split()) if value is not None else None


def _receiver_name(full_name: str) -> str:
    return full_name.rsplit(".", 1)[0] if "." in full_name else ""


def _looks_like_db_receiver(full_name: str) -> bool:
    receiver = _receiver_name(full_name).rsplit(".", 1)[-1].casefold()
    return receiver in {"con", "conn", "connection", "cursor", "cur", "db"} or any(
        marker in full_name.casefold()
        for marker in ("sqlite3.connect(", "_connect(", "open_engine_db_")
    )


def _looks_like_audio_receiver(full_name: str) -> bool:
    receiver = _receiver_name(full_name).rsplit(".", 1)[-1].casefold()
    return receiver in {"a", "audio", "tag", "tags", "metadata"} or any(
        marker in full_name.casefold()
        for marker in ("mutagen.", "id3(", "flac(", "mp4(")
    )


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
    save_calls: dict[tuple[str, str], list[ast.Call]] = {}

    for call in analysis.calls():
        full_name = analysis.call_name(call)
        name = _last_name(full_name)
        symbol = analysis.symbol(call)
        key = (analysis.item.path, symbol)

        if full_name == "sqlite3.connect" and not _is_memory_connect(call):
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

        if name == "commit" and _looks_like_db_receiver(full_name):
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

        if (
            name in {"execute", "executemany"}
            and call.args
            and _looks_like_db_receiver(full_name)
        ):
            sql = _literal_sql(analysis, call.args[0], call)
            if sql is None:
                violations.append(
                    _violation(
                        "unapproved-dynamic-sql",
                        analysis,
                        call,
                        ast.unparse(call),
                        "SQL cannot be resolved statically, so a hidden mutation cannot be excluded",
                        "a static SQL expression or an explicitly reviewed persistence helper",
                    )
                )
            elif _MUTATING_SQL.match(sql):
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

        if name == "save" and _looks_like_audio_receiver(full_name):
            save_counts[key] += 1
            first_save.setdefault(key, call)
            save_calls.setdefault(key, []).append(call)
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
        invalid = [
            call
            for call in save_calls[key]
            if not _verified_backup_dominates(analysis, call, key[1], required_call)
        ]
        for call in invalid:
            violations.append(
                _violation(
                    "audio-backup-call-required",
                    analysis,
                    call,
                    ast.unparse(call),
                    "no verified backup call dominates this save on the same control-flow path",
                    f"{required_call}() before each metadata save",
                )
            )

    return violations


def _definition(analysis: _SourceAnalysis, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    return next(
        (
            node
            for node in ast.walk(analysis.tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ),
        None,
    )


def _is_verified_backup_callable(
    analysis: _SourceAnalysis, function_name: str, required_call: str, save: ast.Call
) -> bool:
    definition = _definition(analysis, required_call)
    if definition is not None:
        return any(
            isinstance(node, ast.Call)
            and _last_name(analysis.call_name(node)) == "create_verified_audio_backup"
            and analysis.symbol(node).endswith(required_call)
            for node in ast.walk(definition)
        )

    function = _definition(analysis, function_name)
    if function is None:
        return False
    parameters = {
        arg.arg
        for arg in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    }
    if required_call not in parameters:
        return False
    return any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == required_call
        and any(isinstance(op, ast.Is) for op in node.test.ops)
        and any(isinstance(value, ast.Constant) and value.value is None for value in node.test.comparators)
        and any(isinstance(child, ast.Raise) for child in ast.walk(node))
        and node.lineno < save.lineno
        for node in ast.walk(function)
    )


def _direct_call_in_statement(
    analysis: _SourceAnalysis, statement: ast.stmt, required_call: str
) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and _last_name(analysis.call_name(statement.value)) == required_call
    )


def _preceding_direct_call(
    analysis: _SourceAnalysis, node: ast.AST, required_call: str
) -> bool:
    current = node
    while current in analysis.parents:
        parent = analysis.parents[current]
        if isinstance(current, ast.stmt):
            for _field, value in ast.iter_fields(parent):
                if isinstance(value, list) and current in value:
                    index = value.index(current)
                    if any(
                        _direct_call_in_statement(analysis, statement, required_call)
                        for statement in value[:index]
                    ):
                        return True
                    break
        current = parent
    return False


def _verified_backup_dominates(
    analysis: _SourceAnalysis, save: ast.Call, function_name: str, required_call: str
) -> bool:
    return _is_verified_backup_callable(analysis, function_name, required_call, save) and _preceding_direct_call(
        analysis, save, required_call
    )


def _direct_function_calls(analysis: _SourceAnalysis, function: str) -> list[ast.Call]:
    node = analysis.functions.get(function)
    if node is None:
        return []
    return [
        call
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and analysis.symbol(call) == function
    ]


def _block_memberships(
    analysis: _SourceAnalysis, node: ast.AST
) -> list[tuple[ast.AST, list[ast.stmt], ast.stmt]]:
    memberships = []
    current = node
    while current in analysis.parents:
        parent = analysis.parents[current]
        if isinstance(current, ast.stmt):
            for _field, value in ast.iter_fields(parent):
                if isinstance(value, list) and current in value:
                    memberships.append((parent, value, current))
                    break
        current = parent
    return memberships


def _queue_is_guaranteed_after(
    analysis: _SourceAnalysis, safe: ast.Call, queue: ast.Call
) -> bool:
    queue_memberships = _block_memberships(analysis, queue)
    for safe_parent, safe_block, safe_statement in _block_memberships(analysis, safe):
        for queue_parent, queue_block, queue_statement in queue_memberships:
            if safe_parent is not queue_parent or safe_block is not queue_block:
                continue
            if safe_block.index(safe_statement) >= safe_block.index(queue_statement):
                continue
            return not isinstance(
                queue_statement,
                (
                    ast.If,
                    ast.For,
                    ast.AsyncFor,
                    ast.While,
                    ast.Try,
                    ast.With,
                    ast.AsyncWith,
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
    return False


def _statically_unreachable(analysis: _SourceAnalysis, node: ast.AST) -> bool:
    current = node
    while current in analysis.parents:
        current = analysis.parents[current]
        if (
            isinstance(current, ast.If)
            and isinstance(current.test, ast.Constant)
            and not current.test.value
        ):
            return True
    return False


def _check_post_commit(analysis: _SourceAnalysis) -> list[Violation]:
    if analysis.item.path != "set_app/set_app.py":
        return []
    violations = []
    for function, required_call in POST_COMMIT_QUEUE_CALLS.items():
        node = analysis.functions.get(function)
        calls = _direct_function_calls(analysis, function)
        queue_calls = [
            call
            for call in calls
            if _last_name(analysis.call_name(call)) == required_call
            and not _statically_unreachable(analysis, call)
        ]
        safe_calls = [
            call
            for call in calls
            if _last_name(analysis.call_name(call)) == "safe_engine_db_write"
        ]
        ordered = bool(queue_calls) and (
            function == "_submit_post_commit_audio_tags"
            or (
                safe_calls
                and all(
                    any(_queue_is_guaranteed_after(analysis, safe, queue) for queue in queue_calls)
                    for safe in safe_calls
                )
            )
        )
        if node is None or not ordered:
            violations.append(
                _violation(
                    "post-commit-queue-required",
                    analysis,
                    node or analysis.tree,
                    function,
                    f"reachable {required_call} must occur after safe_engine_db_write returns",
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


def _check_exact_allowlists(analyses: list[_SourceAnalysis]) -> list[Violation]:
    by_path = {analysis.item.path: analysis for analysis in analyses}
    expected_paths = {
        path
        for policy in (
            SQLITE_CONNECT_ALLOWLIST,
            SQL_MUTATION_ALLOWLIST,
            COMMIT_ALLOWLIST,
            AUDIO_SAVE_ALLOWLIST,
        )
        for path, _symbol in policy
    }
    if not expected_paths.issubset(by_path):
        return []

    observed = {
        "sqlite-connect": Counter(),
        "mutating-sql": Counter(),
        "commit": Counter(),
        "audio-save": Counter(),
    }
    for analysis in analyses:
        for call in analysis.calls():
            full_name = analysis.call_name(call)
            name = _last_name(full_name)
            key = (analysis.item.path, analysis.symbol(call))
            if full_name == "sqlite3.connect" and not _is_memory_connect(call):
                observed["sqlite-connect"][key] += 1
            if name == "commit" and _looks_like_db_receiver(full_name):
                observed["commit"][key] += 1
            if name in {"execute", "executemany"} and call.args and _looks_like_db_receiver(full_name):
                sql = _literal_sql(analysis, call.args[0], call)
                if sql and _MUTATING_SQL.match(sql):
                    observed["mutating-sql"][key] += 1
            if name == "save" and _looks_like_audio_receiver(full_name):
                observed["audio-save"][key] += 1

    violations: list[Violation] = []
    policies = (
        ("sqlite-connect", SQLITE_CONNECT_ALLOWLIST),
        ("mutating-sql", SQL_MUTATION_ALLOWLIST),
        ("commit", COMMIT_ALLOWLIST),
        ("audio-save", AUDIO_SAVE_ALLOWLIST),
    )
    for category, policy in policies:
        for key, (expected, _reason) in policy.items():
            actual = observed[category][key]
            if actual == expected:
                continue
            analysis = by_path[key[0]]
            violations.append(
                _violation(
                    "allowlist-exact-count-mismatch",
                    analysis,
                    analysis.functions.get(key[1].split(".", 1)[0], analysis.tree),
                    f"{category} in {key[1]}",
                    f"policy expects exactly {expected} reviewed call(s), found {actual}",
                    "an explicit architecture review and exact allowlist update",
                )
            )
    return violations


def analyze_sources(items: list[SourceFile]) -> list[Violation]:
    violations = []
    analyses = [_SourceAnalysis(item) for item in items]
    for analysis in analyses:
        violations.extend(_check_calls(analysis))
        violations.extend(_check_post_commit(analysis))
        violations.extend(_check_startup(analysis))
    violations.extend(_check_exact_allowlists(analyses))
    return sorted(violations, key=lambda item: (item.path, item.line, item.rule))


def format_violations(violations: list[Violation]) -> str:
    return "\n".join(str(item) for item in violations)
