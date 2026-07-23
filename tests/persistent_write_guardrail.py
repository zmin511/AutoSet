"""AST checks that keep persistent writes behind AutoSet's safety boundaries."""

from __future__ import annotations

import ast
import hashlib
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
    ("set_app/set_app.py", "export_track_marks_to_engine"): (
        "export_track_marks_to_engine",
        "write_export",
    ),
    ("set_app/set_app.py", "update_genre"): ("update_track_genre", "write_genre"),
    ("set_app/set_app.py", "detail_folder_styles"): (
        "detail_folder_styles",
        "write_detail_styles",
    ),
    ("set_app/set_app.py", "bulk_update_genres"): (
        "bulk_update_genres",
        "write_bulk_genres",
    ),
    ("set_app/set_app.py", "create_engine_playlist_from_tracks"): (
        "create_engine_playlist",
        "write_playlist",
    ),
    ("set_app/set_app.py", "_write_energy_ratings_for_paths"): (
        "write_energy_ratings",
        "write_energy_ratings_batch",
    ),
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
    ("tools/analysis_db.py", "initialize_schema"): (
        1,
        "analysis.db schema creation",
    ),
    ("tools/analysis_db.py", "open_analysis_db"): (
        3,
        "analysis.db connection PRAGMA configuration",
    ),
    ("tools/analysis_db.py", "delete_profile_by_path"): (
        1,
        "delete from AutoSet's separate analysis.db",
    ),
    ("tools/audio_tag_post_commit.py", "_create_indexes"): (
        3,
        "retry-queue schema indexes",
    ),
    ("tools/audio_tag_post_commit.py", "_connect"): (
        2,
        "retry-queue connection PRAGMA configuration",
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
        2,
        "transaction start and connection PRAGMA inside the approved Engine DB safe writer",
    ),
}

SQL_OPERATION_ALLOWLIST = {
    ("set_app/set_app.py", "_insert_playlist"): (
        "INSERT INTO Playlist",
        "UPDATE Playlist",
    ),
    ("set_app/set_app.py", "export_track_marks_to_engine.write_export"): (
        "UPDATE PerformanceData",
        "UPDATE Track",
    ),
    ("set_app/set_app.py", "update_genre.write_genre"): ("UPDATE Track",),
    ("set_app/set_app.py", "detail_folder_styles.write_detail_styles"): (
        "UPDATE Track",
    ),
    ("set_app/set_app.py", "bulk_update_genres.write_bulk_genres"): (
        "UPDATE Track",
    ),
    ("set_app/set_app.py", "create_engine_playlist_from_tracks.write_playlist"): (
        "UPDATE Playlist",
        "UPDATE Playlist",
        "INSERT INTO PlaylistEntity",
        "UPDATE PlaylistEntity",
    ),
    (
        "set_app/set_app.py",
        "_write_energy_ratings_for_paths.write_energy_ratings_batch",
    ): ("UPDATE Track",),
    ("tools/analysis_db.py", "initialize_schema"): ("CREATE TABLE track_analysis",),
    ("tools/analysis_db.py", "open_analysis_db"): (
        "PRAGMA foreign_keys",
        "PRAGMA journal_mode",
        "PRAGMA synchronous",
    ),
    ("tools/analysis_db.py", "upsert_profile"): ("INSERT INTO track_analysis",),
    ("tools/analysis_db.py", "delete_profile_by_path"): (
        "DELETE FROM track_analysis",
    ),
    ("tools/audio_tag_post_commit.py", "_connect"): (
        "PRAGMA busy_timeout",
        "PRAGMA journal_mode",
    ),
    ("tools/audio_tag_post_commit.py", "_create_indexes"): (
        "CREATE INDEX audio_tag_jobs_status_sequence",
        "CREATE INDEX audio_tag_jobs_path_sequence",
        "CREATE INDEX audio_tag_jobs_lease",
    ),
    ("tools/audio_tag_post_commit.py", "_migrate_or_create_schema"): (
        "BEGIN IMMEDIATE",
        "CREATE TABLE audio_tag_jobs",
        "ALTER TABLE audio_tag_jobs",
        "CREATE TABLE audio_tag_jobs",
        "INSERT INTO audio_tag_jobs",
        "DROP TABLE audio_tag_jobs_legacy",
        "UPDATE audio_tag_jobs",
    ),
    ("tools/audio_tag_post_commit.py", "enqueue_audio_tag_jobs"): (
        "BEGIN IMMEDIATE",
        "UPDATE audio_tag_jobs",
        "INSERT INTO audio_tag_jobs",
    ),
    ("tools/audio_tag_post_commit.py", "_claim_job"): (
        "BEGIN IMMEDIATE",
        "UPDATE audio_tag_jobs",
        "UPDATE audio_tag_jobs",
    ),
    ("tools/audio_tag_post_commit.py", "_complete_claim"): (
        "UPDATE audio_tag_jobs",
    ),
    ("tools/engine_db_write.py", "safe_engine_db_write"): (
        "BEGIN IMMEDIATE",
        "PRAGMA foreign_keys",
    ),
}

# Full normalized SQL hashes. Unlike operation/table labels, these make any
# change to columns, predicates, values, schema, or PRAGMA settings explicit.
SQL_FINGERPRINT_ALLOWLIST = {
    ("set_app/set_app.py", "_insert_playlist"): (
        "ab5e0ce2052eefe8ded83809b2e5e02bd6b4191d27d6fa0c90ecfa5444b2aff5",
        "128e8ea5b491f164eb81c24a59c910d0ca1d475af01398319a882cb25db87cdd",
    ),
    ("set_app/set_app.py", "export_track_marks_to_engine.write_export"): (
        "6cdd8d2bcbd32c4096e02beb447d25056f161624fe807254512d545521881815",
        "13ef027a6d1f19f9074c07dc5fd99f44006f3e231161ca9863e433708cbb20c4",
    ),
    ("set_app/set_app.py", "update_genre.write_genre"): (
        "b5ccde251e89c7cb22896dd58b17b132dbfad1295d7e0a37c4f4ce823c15153d",
    ),
    ("set_app/set_app.py", "detail_folder_styles.write_detail_styles"): (
        "b5ccde251e89c7cb22896dd58b17b132dbfad1295d7e0a37c4f4ce823c15153d",
    ),
    ("set_app/set_app.py", "bulk_update_genres.write_bulk_genres"): (
        "b5ccde251e89c7cb22896dd58b17b132dbfad1295d7e0a37c4f4ce823c15153d",
    ),
    ("set_app/set_app.py", "create_engine_playlist_from_tracks.write_playlist"): (
        "eb49fd897e1fdb47b1debd7fb8603d3884aa2b6e6cf60bd934679c51d63debad",
        "eb49fd897e1fdb47b1debd7fb8603d3884aa2b6e6cf60bd934679c51d63debad",
        "e2b00482210ca8bd36f95d3f5830c6417ad146bc2b0464785735c8e723d5c229",
        "9b9133c2dd5c55ee7ae48652b4fc110996dc4942e34cd12fc95552fca9b5fb8a",
    ),
    ("set_app/set_app.py", "_write_energy_ratings_for_paths.write_energy_ratings_batch"): (
        "5725424fdd2362aadc885e9ab32218ca47dae8855edcd405ecd912a54438f4f9",
    ),
    ("tools/analysis_db.py", "open_analysis_db"): (
        "c409d1b0a511a84003321cca8ff14a9736f2e0a7d77b7599746a7f75abe2f2d7",
        "ef39341448ed68658e79774243ef135c26c86fc17c02f3e8ab00a7f87452fef3",
        "4a70a4415f4c4baa2b72b24a85b6b1d7aa91d5796002fa3c160c506c57a9fe5a",
    ),
    ("tools/analysis_db.py", "initialize_schema"): (
        "0c46b82cfb26ca1058227a7535840a9545cb1b11977f987628ff6d897901b274",
    ),
    ("tools/analysis_db.py", "upsert_profile"): (
        "89cfac74ae7087c302286dc9574eb205d00ec0998d945bd1af31cdaca18506ce",
    ),
    ("tools/analysis_db.py", "delete_profile_by_path"): (
        "1d12635c3467dba0ad7633f516d646f46560c2ef12a515ab47e7599557d1caeb",
    ),
    ("tools/audio_tag_post_commit.py", "_create_indexes"): (
        "ec17020112f01185fcac176a039293786fcf854ec5942729c61f3336079ebe15",
        "64141da4a190d1e8ba89e0165086466df04af28d0faee20418e5ec536292ffd8",
        "77d777de74cec697b14281efe233f26ca5cda581ef367813d509407e886858a8",
    ),
    ("tools/audio_tag_post_commit.py", "_connect"): (
        "b20f11154696f10b1dbcd4ae1f086afcf1bc45d9f1c31d34ba99ee92701168d3",
        "ef39341448ed68658e79774243ef135c26c86fc17c02f3e8ab00a7f87452fef3",
    ),
    ("tools/audio_tag_post_commit.py", "_migrate_or_create_schema"): (
        "930a7770399087898ae6ac96ce5375048117486e06b21da4523d2c3c75113c32",
        "c8133b83ab96fa145137e145825079ad6bb84eb71738c565260c36bef7a65af2",
        "46f38c1e7c407287998cd15633b6606f880e9c317712b0aa37be7f16ef1c286b",
        "c8133b83ab96fa145137e145825079ad6bb84eb71738c565260c36bef7a65af2",
        "df4c94a295434393d36049ef3e09ebd44e00fd016613b36e1243c95cd2b00488",
        "cf7db8160a25e93a7ab0c0b228c5931819f16b4afbe69b762c9507c50846b580",
        "d1182c5d2ac43069a91cb19a44b54e847b48fb26d06c20f7c4428ef4cdb70718",
    ),
    ("tools/audio_tag_post_commit.py", "enqueue_audio_tag_jobs"): (
        "930a7770399087898ae6ac96ce5375048117486e06b21da4523d2c3c75113c32",
        "69cc3c26e7d55b5c7e192d76bf1864acdc97b8a4adfa4c499ac54ce6a6a256ea",
        "a58314015433c99f6edc65ccab11565fceec14cf25022d8709eda8f03e8dd828",
    ),
    ("tools/audio_tag_post_commit.py", "_claim_job"): (
        "930a7770399087898ae6ac96ce5375048117486e06b21da4523d2c3c75113c32",
        "ddf5d04d5cac9d89865a3ce0d98e2359ad0634b30a7554a63402d50644ec3ff9",
        "81f2add379d543ae7c6a5205e40227572ae9ec77c82c3d63068e493bcb6628d8",
    ),
    ("tools/audio_tag_post_commit.py", "_complete_claim"): (
        "e3b8e53219b2d427f2df38d82f3c34730cbd0ef3da046deccfd3da137fc86b93",
    ),
    ("tools/engine_db_write.py", "safe_engine_db_write"): (
        "930a7770399087898ae6ac96ce5375048117486e06b21da4523d2c3c75113c32",
        "daf8fd5a565a41345077c9736fe3faee7c42744a31fc509b694bacb9d0ff4b02",
    ),
}

# These production reads necessarily construct identifiers or placeholder lists
# at runtime.  They are approved by exact path/symbol, call count, and an AST
# fingerprint of the SQL expression; every other incomplete SQL expression is
# rejected fail-closed.
DYNAMIC_SQL_READ_ALLOWLIST = {
    ("set_app/set_app.py", "engine_db_diagnostics"): (
        "be3985351f933e9e4f6fc12ef3508b706a8d35bf74b389741b67469d1021e8ad",
        "2ed59d463efd2dd69cfbb9aaf3e2b58651279513ee79f01aff20b886cfd565f6",
    ),
    ("set_app/set_app.py", "_load_track_maps_for_files_from_connection"): (
        "860e25845fa6f05b9782f20df35338cae29ab6ee1b4e036c99e3988a7310ea07",
        "a5e922f9e3dac945a73e3d3d6b4679ce20742672358e76f251f9ee004e9ceb7f",
    ),
    ("set_app/set_app.py", "attach_energy"): (
        "0f739f449a8f60a5d39f6483c294f0ed3b8ee2549324e9a66d289d53d3b18182",
    ),
    ("set_app/set_app.py", "_table_has_column"): (
        "fa05afc28c3af0a61df56aaa26d93179aa23573d33ff95899552f89205ae67f6",
    ),
    ("tools/audio_tag_post_commit.py", "_candidate_jobs"): (
        "99027c22c128e26acfc1c34304a443ef48881cb2429267917a1ab36cb37686a0",
    ),
    ("tools/audio_tag_post_commit.py", "_jobs_by_id"): (
        "405ba299eea5d099cf59eedfd689313551eaf5832a01eafe55d28e868eb8df1e",
    ),
    ("tools/engine_db_diff_cues.py", "fetch_rows"): (
        "4f992f2bdc1a43c1164634661f022d6c394199a9f056a0b217136f1649f35887",
    ),
    ("tools/engine_db_diff_cues.py", "table_schema"): (
        "8831a5470d5a5622194e048788ad7a452ff59c9e1f946943b24b6a9a34e4e952",
    ),
    ("tools/engine_set_builder.py", "_row_has_column"): (
        "b41305afb53135356efd4b219f287d6f3b347b597518d8127d9b0cb98f2b2381",
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

POST_COMMIT_QUEUE_ORIGINS = {
    "_submit_post_commit_audio_tags": "_submit_post_commit_audio_tags",
    "submit_audio_tag_jobs": "audio_tag_post_commit.submit_audio_tag_jobs",
}

# Dynamic reflection is fail-closed because it can manufacture any of the
# persistence callables below without leaving a resolvable attribute in the
# AST.  This one helper is reviewed data access and never invokes the result.
DYNAMIC_GETATTR_ALLOWLIST = {
    ("tools/track_analysis.py", "_value_from_source"): (
        1,
        "generic attribute-or-mapping read helper",
    ),
}

REFLECTIVE_ATTRIBUTE_ALLOWLIST = {
    ("tools/engine_set_builder.py", "load_tracks", "__dict__"): (
        1,
        "copy reviewed Track dataclass fields into a replacement Track",
    ),
}

REFLECTIVE_ATTRIBUTES = {"__dict__", "__mro__", "__subclasses__"}

FORBIDDEN_REFLECTION_CALLS = {
    "__import__",
    "__getattribute__",
    "attrgetter",
    "compile",
    "eval",
    "exec",
    "globals",
    "import_module",
    "locals",
    "methodcaller",
    "vars",
}

AUDIO_CALLBACK_WRITERS = {
    "_set_tags_mp3": 4,
    "_set_bitrate_tag_mp3": 3,
    "_set_tags_flac": 4,
    "_set_bitrate_tag_flac": 3,
}

DANGEROUS_CALLABLE_NAMES = {
    "Connection",
    "commit",
    "connect",
    "execute",
    "executemany",
    "executescript",
    "safe_engine_db_write",
    "save",
    "submit_audio_tag_jobs",
    "write_audio_tags",
    "write_tags",
    *AUDIO_CALLBACK_WRITERS,
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

_SQL_COMMENT = re.compile(r"/\*.*?\*/|--[^\n]*(?:\n|$)", re.DOTALL)
_SQL_WRITE = re.compile(
    r"\b(INSERT\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|"
    r"CREATE\s+(?:(?:UNIQUE|VIRTUAL|TEMP|TEMPORARY)\s+)*(?:TABLE|INDEX|TRIGGER|VIEW)|"
    r"DROP\s+(?:TABLE|INDEX|TRIGGER|VIEW)|ALTER\s+TABLE|"
    r"BEGIN(?:\s+IMMEDIATE|\s+EXCLUSIVE)?|VACUUM|ATTACH|DETACH)\b",
    re.IGNORECASE,
)
_PRAGMA = re.compile(
    r"^PRAGMA\s+(?:[\w]+\.)?([\w]+)(.*)$",
    re.IGNORECASE | re.DOTALL,
)
_READ_ONLY_PRAGMA_CALLS = {
    "foreign_key_check",
    "foreign_key_list",
    "index_info",
    "index_list",
    "index_xinfo",
    "integrity_check",
    "quick_check",
    "table_info",
    "table_list",
    "table_xinfo",
}
_READ_ONLY_PRAGMA_VALUES = {"foreign_keys"}


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
        self.annotation_nodes = self._annotation_nodes()
        self.functions = {
            node.name: node
            for node in self.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _imports(self) -> dict[tuple[str, str], list[tuple[int, str]]]:
        """Collect imports per lexical scope instead of flattening the file."""
        aliases: dict[tuple[str, str], list[tuple[int, str]]] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    local_name = name.asname or name.name.split(".")[0]
                    aliases.setdefault((self.symbol(node), local_name), []).append(
                        (node.lineno, name.name)
                    )
            elif isinstance(node, ast.ImportFrom):
                for name in node.names:
                    qualified = f"{node.module}.{name.name}" if node.module else name.name
                    aliases.setdefault(
                        (self.symbol(node), name.asname or name.name), []
                    ).append((node.lineno, qualified))
        return aliases

    def _import_name(self, name: str, context: ast.AST) -> str | None:
        line = getattr(context, "lineno", 10**9)
        symbol = self.symbol(context)
        scopes = []
        if symbol != "<module>":
            parts = symbol.split(".")
            scopes.extend(".".join(parts[:size]) for size in range(len(parts), 0, -1))
        scopes.append("<module>")
        for scope in scopes:
            candidates = self.imports.get((scope, name), [])
            if scope != "<module>" or symbol == "<module>":
                candidates = [item for item in candidates if item[0] <= line]
            if candidates:
                return max(candidates, key=lambda item: item[0])[1]
        return None

    def _annotation_nodes(self) -> set[ast.AST]:
        annotations: set[ast.AST] = set()
        for node in ast.walk(self.tree):
            roots: list[ast.AST | None] = []
            if isinstance(node, ast.arg):
                roots.append(node.annotation)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                roots.append(node.returns)
            elif isinstance(node, ast.AnnAssign):
                roots.append(node.annotation)
            for root in roots:
                if root is not None:
                    annotations.update(ast.walk(root))
        return annotations

    @staticmethod
    def _target_bindings(target: ast.AST, value: ast.AST) -> list[tuple[str, ast.AST]]:
        """Pair assignment targets with the value expression they receive."""
        if isinstance(target, ast.Name):
            return [(target.id, value)]
        if isinstance(target, (ast.Tuple, ast.List)) and isinstance(
            value, (ast.Tuple, ast.List)
        ):
            if len(target.elts) == len(value.elts):
                result: list[tuple[str, ast.AST]] = []
                for child_target, child_value in zip(
                    target.elts, value.elts, strict=True
                ):
                    result.extend(
                        _SourceAnalysis._target_bindings(child_target, child_value)
                    )
                return result
        return []

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
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                value = node.iter
                targets = [node.target]
            elif isinstance(node, ast.comprehension):
                value = node.iter
                targets = [node.target]
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                value, targets = node, [ast.Name(id=node.name)]
            if value is None:
                continue
            for target in targets:
                values = (
                    value.elts
                    if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension))
                    and isinstance(value, (ast.List, ast.Tuple, ast.Set))
                    else [value]
                )
                for candidate in values:
                    for name, bound_value in self._target_bindings(target, candidate):
                        bindings.setdefault((self.symbol(node), name), []).append(
                            (
                                getattr(node, "lineno", getattr(target, "lineno", 1)),
                                bound_value,
                            )
                        )
        return bindings

    def _binding_candidates(self, name: str, context: ast.AST) -> list[ast.AST]:
        """Return every value a nearest visible binding may produce."""
        def merge(*groups: list[ast.AST]) -> list[ast.AST]:
            result: list[ast.AST] = []
            for value in (item for group in groups for item in group):
                if value not in result:
                    result.append(value)
            return result

        def assigned_values(node: ast.AST) -> list[ast.AST] | None:
            value: ast.AST | None = None
            targets: list[ast.AST] = []
            if isinstance(node, ast.Assign):
                value, targets = node.value, node.targets
            elif isinstance(node, ast.AnnAssign):
                value, targets = node.value, [node.target]
            elif isinstance(node, ast.NamedExpr):
                value, targets = node.value, [node.target]
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                value, targets = node, [ast.Name(id=node.name)]
            if value is None:
                return None
            values = [
                bound_value
                for target in targets
                for bound_name, bound_value in self._target_bindings(target, value)
                if bound_name == name
            ]
            return values or None

        def contains(root: ast.AST, target: ast.AST) -> bool:
            current = target
            while current in self.parents:
                current = self.parents[current]
                if current is root:
                    return True
            return root is target

        def flow_complete(node: ast.stmt, state: list[ast.AST]) -> list[ast.AST]:
            if (
                isinstance(node, ast.AugAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == name
            ):
                return [
                    ast.BinOp(left=value, op=node.op, right=node.value)
                    for value in state
                ] or [
                    ast.BinOp(
                        left=ast.Name(id=name, ctx=ast.Load()),
                        op=node.op,
                        right=node.value,
                    )
                ]
            direct = assigned_values(node)
            if direct is not None:
                return direct
            if isinstance(node, ast.If):
                body = flow_block(node.body, state)
                orelse = flow_block(node.orelse, state) if node.orelse else state
                return merge(body, orelse)
            if isinstance(node, (ast.For, ast.AsyncFor)):
                loop_values: list[ast.AST] = []
                candidates = (
                    node.iter.elts
                    if isinstance(node.iter, (ast.List, ast.Tuple, ast.Set))
                    else [node.iter]
                )
                for candidate in candidates:
                    loop_values.extend(
                        bound_value
                        for bound_name, bound_value in self._target_bindings(
                            node.target, candidate
                        )
                        if bound_name == name
                    )
                body = flow_block(node.body, loop_values or state)
                result = merge(state, body)
                return flow_block(node.orelse, result) if node.orelse else result
            if isinstance(node, ast.While):
                body = flow_block(node.body, state)
                result = merge(state, body)
                return flow_block(node.orelse, result) if node.orelse else result
            if isinstance(node, (ast.With, ast.AsyncWith)):
                return flow_block(node.body, state)
            if isinstance(node, ast.Try):
                normal = flow_block(node.orelse, flow_block(node.body, state))
                handlers = [flow_block(handler.body, state) for handler in node.handlers]
                result = merge(normal, *handlers)
                return flow_block(node.finalbody, result)
            if isinstance(node, ast.Match):
                return merge(
                    state,
                    *(flow_block(case.body, state) for case in node.cases),
                )
            return state

        def flow_to_target(
            node: ast.stmt,
            state: list[ast.AST],
        ) -> list[ast.AST]:
            if isinstance(node, ast.If):
                if contains(node.test, context):
                    return state
                branch = node.body if any(contains(item, context) for item in node.body) else node.orelse
                return flow_block(branch, state, context)
            if isinstance(node, (ast.For, ast.AsyncFor)):
                if contains(node.iter, context):
                    return state
                loop_state = state
                candidates = (
                    node.iter.elts
                    if isinstance(node.iter, (ast.List, ast.Tuple, ast.Set))
                    else [node.iter]
                )
                values = [
                    bound_value
                    for candidate in candidates
                    for bound_name, bound_value in self._target_bindings(
                        node.target, candidate
                    )
                    if bound_name == name
                ]
                if values:
                    loop_state = values
                branch = node.body if any(contains(item, context) for item in node.body) else node.orelse
                return flow_block(branch, loop_state, context)
            if isinstance(node, ast.While):
                if contains(node.test, context):
                    return state
                branch = node.body if any(contains(item, context) for item in node.body) else node.orelse
                return flow_block(branch, state, context)
            if isinstance(node, (ast.With, ast.AsyncWith)):
                return flow_block(node.body, state, context)
            if isinstance(node, ast.Try):
                branches = [node.body, node.orelse, node.finalbody]
                branches.extend(handler.body for handler in node.handlers)
                for branch in branches:
                    if any(contains(item, context) for item in branch):
                        return flow_block(branch, state, context)
            if isinstance(node, ast.Match):
                for case in node.cases:
                    if any(contains(item, context) for item in case.body):
                        return flow_block(case.body, state, context)
            return state

        def flow_block(
            statements: list[ast.stmt],
            initial: list[ast.AST],
            target: ast.AST | None = None,
        ) -> list[ast.AST]:
            state = initial
            for statement in statements:
                if target is not None and contains(statement, target):
                    return flow_to_target(statement, state)
                if isinstance(
                    statement,
                    (ast.Return, ast.Raise, ast.Break, ast.Continue),
                ):
                    return []
                state = flow_complete(statement, state)
            return state

        scopes: list[ast.AST] = []
        current = context
        while current in self.parents:
            current = self.parents[current]
            if isinstance(
                current,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Module),
            ):
                scopes.append(current)
        for scope in scopes:
            if isinstance(scope, ast.Lambda):
                continue
            candidates = flow_block(scope.body, [], context)
            if candidates:
                return candidates
        line = getattr(context, "lineno", 10**9)
        symbol = self.symbol(context)
        fallback = [
            value
            for binding_line, value in self.bindings.get((symbol, name), [])
            if binding_line <= line
        ]
        if fallback:
            latest = max(
                binding_line
                for binding_line, _value in self.bindings[(symbol, name)]
                if binding_line <= line
            )
            return [
                value
                for binding_line, value in self.bindings[(symbol, name)]
                if binding_line == latest
            ]
        return []

    def _binding(self, name: str, context: ast.AST) -> ast.AST | None:
        """Return the latest simple assignment visible before *context*."""
        candidates = self._binding_candidates(name, context)
        return candidates[0] if candidates else None

    def _parameter_default(self, name: str, context: ast.AST) -> ast.AST | None:
        current = context
        while current in self.parents:
            current = self.parents[current]
            if not isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            positional = [*current.args.posonlyargs, *current.args.args]
            defaulted_positional = (
                positional[-len(current.args.defaults) :]
                if current.args.defaults
                else []
            )
            positional_defaults = {
                argument.arg: default
                for argument, default in zip(
                    defaulted_positional,
                    current.args.defaults,
                    strict=True,
                )
            }
            keyword_defaults = {
                argument.arg: default
                for argument, default in zip(
                    current.args.kwonlyargs,
                    current.args.kw_defaults,
                    strict=True,
                )
                if default is not None
            }
            return positional_defaults.get(name) or keyword_defaults.get(name)
        return None

    def _parameter_shadows_import(self, name: str, context: ast.AST) -> bool:
        current = context
        while current in self.parents:
            current = self.parents[current]
            if not isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            arguments = (
                *current.args.posonlyargs,
                *current.args.args,
                *current.args.kwonlyargs,
            )
            return name in {argument.arg for argument in arguments} or (
                current.args.vararg is not None and current.args.vararg.arg == name
            ) or (
                current.args.kwarg is not None and current.args.kwarg.arg == name
            )
        return False

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
            if node.id not in seen:
                binding = self._binding(node.id, context)
                if binding is not None:
                    return self.expression_name(binding, context, seen | {node.id})
                default = self._parameter_default(node.id, context)
                if default is not None and not (
                    isinstance(default, ast.Constant) and default.value is None
                ):
                    return self.expression_name(default, context, seen | {node.id})
            imported = self._import_name(node.id, context)
            if imported is not None and not self._parameter_shadows_import(node.id, context):
                return imported
            return node.id
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            owner = self.symbol(node)
            return f"{owner}.{node.name}" if owner != "<module>" else node.name
        if isinstance(node, ast.Attribute):
            base = self.expression_name(node.value, context, seen)
            return f"{base}.{node.attr}" if base else node.attr
        if isinstance(node, ast.Subscript):
            selected = self._subscript_value(node, context)
            if selected is not None:
                return self.expression_name(selected, context, seen)
        if isinstance(node, ast.Call):
            called = self.expression_name(node.func, context, seen)
            if called == "getattr" and len(node.args) >= 2:
                attribute = _static_string(self, node.args[1], context)
                if attribute is not None:
                    base = self.expression_name(node.args[0], context, seen)
                    return f"{base}.{attribute}"
            if called == "__import__" and node.args:
                module = _static_constant_string(node.args[0])
                if module is not None:
                    return module
            return f"{called}()"
        return ast.unparse(node)

    def expression_names(
        self,
        node: ast.AST,
        context: ast.AST | None = None,
        seen: frozenset[str] = frozenset(),
    ) -> set[str]:
        """Resolve every statically possible callable name conservatively."""
        context = context or node
        if isinstance(node, ast.Name):
            if node.id not in seen:
                bindings = self._binding_candidates(node.id, context)
                if bindings:
                    return {
                        name
                        for binding in bindings
                        for name in self.expression_names(
                            binding, context, seen | {node.id}
                        )
                    }
                default = self._parameter_default(node.id, context)
                if default is not None and not (
                    isinstance(default, ast.Constant) and default.value is None
                ):
                    return self.expression_names(default, context, seen | {node.id})
            imported = self._import_name(node.id, context)
            if imported is not None and not self._parameter_shadows_import(node.id, context):
                return {imported}
            return {node.id}
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            owner = self.symbol(node)
            return {f"{owner}.{node.name}" if owner != "<module>" else node.name}
        if isinstance(node, ast.Attribute):
            return {
                f"{base}.{node.attr}" if base else node.attr
                for base in self.expression_names(node.value, context, seen)
            }
        if isinstance(node, ast.IfExp):
            return self.expression_names(
                node.body, context, seen
            ) | self.expression_names(node.orelse, context, seen)
        if isinstance(node, ast.BoolOp):
            return {
                name
                for value in node.values
                for name in self.expression_names(value, context, seen)
            }
        if isinstance(node, ast.Subscript):
            selected = self._subscript_values(node, context)
            if selected:
                return {
                    name
                    for value in selected
                    for name in self.expression_names(value, context, seen)
                }
        if isinstance(node, ast.Call):
            called_names = self.expression_names(node.func, context, seen)
            if "getattr" in called_names and len(node.args) >= 2:
                attribute = _static_string(self, node.args[1], context)
                if attribute is not None:
                    return {
                        f"{base}.{attribute}"
                        for base in self.expression_names(node.args[0], context, seen)
                    }
            if "__import__" in called_names and node.args:
                module = _static_constant_string(node.args[0])
                if module is not None:
                    return {module}
            return {f"{called}()" for called in called_names}
        return {ast.unparse(node)}

    def _subscript_value(self, node: ast.Subscript, context: ast.AST) -> ast.AST | None:
        values = self._subscript_values(node, context)
        return values[0] if values else None

    def _subscript_values(self, node: ast.Subscript, context: ast.AST) -> list[ast.AST]:
        container = node.value
        if isinstance(container, ast.Name):
            container = self._binding(container.id, context) or container
        key = _static_string(self, node.slice, context)
        if isinstance(container, ast.Dict) and key is not None:
            for item_key, item_value in zip(
                container.keys, container.values, strict=True
            ):
                if item_key is not None and _static_string(self, item_key, context) == key:
                    return [item_value]
        if isinstance(container, ast.Dict) and key is None:
            return list(container.values)
        if isinstance(container, (ast.List, ast.Tuple)):
            index = node.slice.value if isinstance(node.slice, ast.Constant) else None
            if isinstance(index, int) and -len(container.elts) <= index < len(container.elts):
                return [container.elts[index]]
            if index is None:
                return list(container.elts)
        return []

    def call_name(self, node: ast.Call) -> str:
        return self.expression_name(node.func, node)

    def call_names(self, node: ast.Call) -> set[str]:
        return self.expression_names(node.func, node)

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


def _only_last_name(analysis: _SourceAnalysis, node: ast.AST, context: ast.AST) -> str:
    names = {_last_name(name) for name in analysis.expression_names(node, context)}
    return next(iter(names)) if len(names) == 1 else ""


def _static_constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


_UNKNOWN_STATIC_VALUE = object()


def _static_format_value(
    analysis: _SourceAnalysis,
    node: ast.AST,
    context: ast.AST,
    seen: frozenset[str],
) -> object:
    """Resolve only inert constants that Python string formatting can consume."""
    if isinstance(node, ast.Constant) and isinstance(
        node.value, (str, bytes, int, float, complex, bool, type(None))
    ):
        return node.value
    if isinstance(node, ast.Name) and node.id not in seen:
        bindings = analysis._binding_candidates(node.id, context)
        if bindings:
            values = [
                _static_format_value(
                    analysis, binding, context, seen | {node.id}
                )
                for binding in bindings
            ]
            if all(value is not _UNKNOWN_STATIC_VALUE for value in values):
                first = values[0]
                if all(value == first for value in values[1:]):
                    return first
    if isinstance(node, ast.Tuple):
        values = [
            _static_format_value(analysis, item, context, seen)
            for item in node.elts
        ]
        if all(value is not _UNKNOWN_STATIC_VALUE for value in values):
            return tuple(values)
    return _UNKNOWN_STATIC_VALUE


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
        bindings = analysis._binding_candidates(node.id, context)
        if bindings:
            values = [
                _static_string(analysis, binding, context, seen | {node.id})
                for binding in bindings
            ]
            if all(value is not None for value in values):
                unique = set(values)
                if len(unique) == 1:
                    return values[0]
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
                continue
            if not isinstance(value, ast.FormattedValue):
                return None
            resolved = _static_format_value(
                analysis, value.value, context, seen
            )
            if resolved is _UNKNOWN_STATIC_VALUE:
                return None
            if value.conversion == ord("s"):
                resolved = str(resolved)
            elif value.conversion == ord("r"):
                resolved = repr(resolved)
            elif value.conversion == ord("a"):
                resolved = ascii(resolved)
            elif value.conversion != -1:
                return None
            format_spec = (
                ""
                if value.format_spec is None
                else _static_string(
                    analysis, value.format_spec, context, seen
                )
            )
            if format_spec is None:
                return None
            try:
                parts.append(format(resolved, format_spec))
            except (OverflowError, TypeError, ValueError):
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        left = _static_string(analysis, node.left, context, seen)
        if isinstance(node.op, ast.Add):
            right = _static_string(analysis, node.right, context, seen)
            if left is not None and right is not None:
                return left + right
        elif left is not None:
            right = _static_format_value(
                analysis, node.right, context, seen
            )
            if right is not _UNKNOWN_STATIC_VALUE:
                try:
                    result = left % right
                except (OverflowError, TypeError, ValueError):
                    return None
                return result if isinstance(result, str) else None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    ):
        template = _static_string(
            analysis, node.func.value, context, seen
        )
        if template is None or any(
            isinstance(argument, ast.Starred) for argument in node.args
        ) or any(keyword.arg is None for keyword in node.keywords):
            return None
        arguments = [
            _static_format_value(analysis, argument, context, seen)
            for argument in node.args
        ]
        keywords = {
            keyword.arg: _static_format_value(
                analysis, keyword.value, context, seen
            )
            for keyword in node.keywords
            if keyword.arg is not None
        }
        if any(
            value is _UNKNOWN_STATIC_VALUE
            for value in (*arguments, *keywords.values())
        ):
            return None
        try:
            return template.format(*arguments, **keywords)
        except (
            AttributeError,
            IndexError,
            KeyError,
            OverflowError,
            TypeError,
            ValueError,
        ):
            return None
    return None


def _sql_template(
    analysis: _SourceAnalysis,
    node: ast.AST,
    context: ast.AST,
    seen: frozenset[str] = frozenset(),
) -> str | None:
    """Resolve the visible SQL skeleton while marking unknown substitutions."""
    exact = _static_string(analysis, node, context, seen)
    if exact is not None:
        return exact
    if isinstance(node, ast.Name) and node.id not in seen:
        bindings = analysis._binding_candidates(node.id, context)
        templates = {
            _sql_template(analysis, binding, context, seen | {node.id})
            for binding in bindings
        }
        if len(templates) == 1:
            return templates.pop()
        return None
    if isinstance(node, ast.JoinedStr):
        return "".join(
            value.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
            else "?"
            for value in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        left = _sql_template(analysis, node.left, context, seen)
        if isinstance(node.op, ast.Mod):
            return left
        right = _sql_template(analysis, node.right, context, seen)
        if left is not None and right is not None:
            return left + right
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    ):
        return _sql_template(analysis, node.func.value, context, seen)
    return None


def _literal_sql(analysis: _SourceAnalysis, node: ast.AST, context: ast.AST) -> str | None:
    return _sql_template(analysis, node, context)


def _literal_sql_candidates(
    analysis: _SourceAnalysis,
    node: ast.AST,
    context: ast.AST,
    seen: frozenset[str] = frozenset(),
) -> list[str | None]:
    """Return each statically reachable complete SQL value."""
    if isinstance(node, ast.Name) and node.id not in seen:
        bindings = analysis._binding_candidates(node.id, context)
        if bindings:
            return [
                candidate
                for binding in bindings
                for candidate in _literal_sql_candidates(
                    analysis, binding, context, seen | {node.id}
                )
            ]
    if isinstance(node, ast.IfExp):
        return _literal_sql_candidates(
            analysis, node.body, context, seen
        ) + _literal_sql_candidates(analysis, node.orelse, context, seen)
    return [_static_string(analysis, node, context, seen)]


def _normalized_sql(sql: str) -> str:
    return " ".join(_SQL_COMMENT.sub(" ", sql).split())


def _sql_write_signature(sql: str) -> str | None:
    normalized = _normalized_sql(sql)
    pragma = _PRAGMA.match(normalized)
    if pragma:
        name = pragma.group(1).casefold()
        suffix = pragma.group(2).strip()
        read_only = (
            name in _READ_ONLY_PRAGMA_VALUES and not suffix
        ) or (
            name in _READ_ONLY_PRAGMA_CALLS
            and (not suffix or (suffix.startswith("(") and suffix.endswith(")")))
        )
        return None if read_only else f"PRAGMA {name}"
    match = _SQL_WRITE.search(normalized)
    if match is None:
        return None
    operation = " ".join(match.group(1).upper().split())
    tail = normalized[match.end() :].lstrip()
    target = re.match(
        r"(?:IF\s+NOT\s+EXISTS\s+|IF\s+EXISTS\s+)?[\"`\[]?([\w.]+)",
        tail,
        re.IGNORECASE,
    )
    if operation.startswith("BEGIN") or operation in {"VACUUM", "ATTACH", "DETACH"}:
        return operation
    return f"{operation} {target.group(1) if target else '<dynamic>'}"


def _sql_fingerprint(sql: str) -> str:
    return hashlib.sha256(_normalized_sql(sql).encode("utf-8")).hexdigest()


def _expression_fingerprint(
    analysis: _SourceAnalysis,
    node: ast.AST,
    context: ast.AST,
    seen: frozenset[str] = frozenset(),
) -> str:
    rendered = ast.dump(node, include_attributes=False)
    if isinstance(node, ast.Name) and node.id not in seen:
        bindings = analysis._binding_candidates(node.id, context)
        rendered += "|" + "|".join(
            sorted(
                _expression_fingerprint(
                    analysis, binding, context, seen | {node.id}
                )
                for binding in bindings
            )
        )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _is_approved_incomplete_sql(
    analysis: _SourceAnalysis,
    node: ast.AST,
    context: ast.AST,
    template: str | None,
) -> bool:
    key = (analysis.item.path, analysis.symbol(context))
    if _expression_fingerprint(
        analysis, node, context
    ) in DYNAMIC_SQL_READ_ALLOWLIST.get(key, ()):
        return True
    if template is None or _sql_write_signature(template) is None:
        return False
    return _sql_fingerprint(template) in SQL_FINGERPRINT_ALLOWLIST.get(key, ())


def _is_sqlite_opener_expression(
    analysis: _SourceAnalysis,
    node: ast.AST,
    context: ast.AST,
) -> bool:
    """Recognize equivalent ways of invoking sqlite3's writable openers."""
    resolved = analysis.expression_names(node, context)
    if resolved & {
        "sqlite3.connect",
        "sqlite3.Connection",
        "sqlite3.dbapi2.connect",
        "sqlite3.dbapi2.Connection",
    }:
        return True
    if isinstance(node, ast.Attribute) and node.attr == "__call__":
        return _is_sqlite_opener_expression(analysis, node.value, context)
    if isinstance(node, ast.Call):
        called = analysis.expression_names(node.func, context)
        if any(_last_name(name) == "partial" for name in called) and node.args:
            return _is_sqlite_opener_expression(analysis, node.args[0], context)
    if (
        isinstance(node, ast.Subscript)
        and _static_constant_string(node.slice) in {"connect", "Connection"}
        and isinstance(node.value, ast.Call)
        and _last_name(analysis.expression_name(node.value.func, context)) == "vars"
        and node.value.args
        and "sqlite3" in analysis.expression_names(node.value.args[0], context)
    ):
        return True
    return False


def _is_sqlite_opener_call(analysis: _SourceAnalysis, call: ast.Call) -> bool:
    return _is_sqlite_opener_expression(analysis, call.func, call)


def _is_approved_safe_write_call(analysis: _SourceAnalysis, call: ast.Call) -> bool:
    return analysis.call_names(call) == {"engine_db_write.safe_engine_db_write"}


def _sql_invocation(
    analysis: _SourceAnalysis, call: ast.Call
) -> tuple[str, ast.AST] | None:
    """Return the SQL method and expression for direct and methodcaller calls."""
    names = {_last_name(name) for name in analysis.call_names(call)}
    methods = names & {"execute", "executemany", "executescript"}
    if methods and call.args:
        return sorted(methods)[0], call.args[0]
    if isinstance(call.func, ast.Call):
        factories = analysis.expression_names(call.func.func, call)
        method = _static_string(analysis, call.func.args[0], call) if call.func.args else None
        if "operator.methodcaller" in factories and method in {
            "execute",
            "executemany",
            "executescript",
        } and len(call.func.args) >= 2:
            return method, call.func.args[1]
    return None


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


def _module_imports_mutagen(analysis: _SourceAnalysis) -> bool:
    return any(
        name == "mutagen" or name.startswith("mutagen.")
        for candidates in analysis.imports.values()
        for _line, name in candidates
    )


def _safe_write_signature(
    analysis: _SourceAnalysis, call: ast.Call
) -> tuple[str | None, str | None]:
    operation = (
        _static_string(analysis, call.args[2], call)
        if len(call.args) >= 3
        else None
    )
    callback = (
        _only_last_name(analysis, call.args[3], call)
        if len(call.args) >= 4
        else None
    )
    return operation, callback


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


def _is_direct_call_target(analysis: _SourceAnalysis, node: ast.AST) -> bool:
    parent = analysis.parents.get(node)
    return isinstance(parent, ast.Call) and parent.func is node


def _check_capability_policy(analysis: _SourceAnalysis) -> list[Violation]:
    """Reject persistence callables as values and unreviewed reflection.

    Direct calls continue through the exact call/SQL/backup allowlists.  Taking
    a dangerous callable as a value is denied before adapters such as partial,
    map, containers, decorators, or user-defined dispatchers can hide the call.
    """
    violations: list[Violation] = []
    reflective_counts: Counter[tuple[str, str, str]] = Counter()

    for node in ast.walk(analysis.tree):
        if isinstance(node, ast.ImportFrom) and any(
            alias.name == "*" for alias in node.names
        ):
            violations.append(
                _violation(
                    "unreviewed-wildcard-import",
                    analysis,
                    node,
                    ast.unparse(node),
                    "wildcard imports hide the origin of persistence callables",
                    "explicit imported names",
                )
            )

        if isinstance(node, ast.Attribute) and node.attr in REFLECTIVE_ATTRIBUTES:
            key = (analysis.item.path, analysis.symbol(node), node.attr)
            reflective_counts[key] += 1
            allowed = REFLECTIVE_ATTRIBUTE_ALLOWLIST.get(key)
            if allowed is None or reflective_counts[key] > allowed[0]:
                violations.append(
                    _violation(
                        "unreviewed-reflective-attribute",
                        analysis,
                        node,
                        ast.unparse(node),
                        f"reflective attribute {node.attr!r} can expose hidden callables",
                        "an exact REFLECTIVE_ATTRIBUTE_ALLOWLIST entry after review",
                    )
                )

        if (
            isinstance(node, (ast.Name, ast.Attribute))
            and isinstance(getattr(node, "ctx", None), ast.Load)
            and node not in analysis.annotation_nodes
            and not _is_direct_call_target(analysis, node)
        ):
            names = analysis.expression_names(node, node)
            dangerous = sorted(
                name for name in names if _last_name(name) in DANGEROUS_CALLABLE_NAMES
            )
            if dangerous:
                violations.append(
                    _violation(
                        "persistent-callable-transfer",
                        analysis,
                        node,
                        ast.unparse(node),
                        f"dangerous callable is used as a value: {dangerous!r}",
                        "a direct reviewed call covered by the exact persistence allowlists",
                    )
                )

        if not isinstance(node, ast.Call):
            continue
        called_names = analysis.call_names(node)
        called_last = {_last_name(name) for name in called_names}
        if "getattr" in called_last:
            attribute = (
                _static_string(analysis, node.args[1], node)
                if len(node.args) >= 2
                else None
            )
            if attribute in DANGEROUS_CALLABLE_NAMES:
                violations.append(
                    _violation(
                        "dynamic-persistence-capability",
                        analysis,
                        node,
                        ast.unparse(node),
                        f"getattr obtains persistence capability {attribute!r}",
                        "a direct reviewed persistence call",
                    )
                )
            elif attribute is None:
                key = (analysis.item.path, analysis.symbol(node))
                if key not in DYNAMIC_GETATTR_ALLOWLIST:
                    violations.append(
                        _violation(
                            "unreviewed-dynamic-getattr",
                            analysis,
                            node,
                            ast.unparse(node),
                            "dynamic attribute lookup could manufacture a hidden persistence callable",
                            "a static attribute name or an exact DYNAMIC_GETATTR_ALLOWLIST entry",
                        )
                    )

        forbidden = sorted(
            name
            for name in called_names
            if name in FORBIDDEN_REFLECTION_CALLS
            or name in {
                "builtins.__import__",
                "builtins.compile",
                "builtins.eval",
                "builtins.exec",
                "builtins.globals",
                "builtins.locals",
                "builtins.vars",
                "importlib.import_module",
                "inspect.getattr_static",
                "inspect.getmembers",
                "inspect.getmembers_static",
                "operator.attrgetter",
                "operator.methodcaller",
            }
            or _last_name(name) == "__getattribute__"
        )
        if forbidden:
            violations.append(
                _violation(
                    "unreviewed-reflective-call",
                    analysis,
                    node,
                    ast.unparse(node),
                    f"reflection/callable factory is fail-closed: {forbidden!r}",
                    "direct imports and direct reviewed persistence calls",
                )
            )

    return violations


def _check_calls(analysis: _SourceAnalysis) -> list[Violation]:
    violations: list[Violation] = []
    connect_counts: Counter[tuple[str, str]] = Counter()
    commit_counts: Counter[tuple[str, str]] = Counter()
    mutation_counts: Counter[tuple[str, str]] = Counter()
    save_counts: Counter[tuple[str, str]] = Counter()
    first_save: dict[tuple[str, str], ast.Call] = {}
    save_calls: dict[tuple[str, str], list[ast.Call]] = {}

    for call in analysis.calls():
        names = {_last_name(name) for name in analysis.call_names(call)}
        symbol = analysis.symbol(call)
        key = (analysis.item.path, symbol)

        if _is_sqlite_opener_call(analysis, call) and not _is_memory_connect(call):
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

        if "safe_engine_db_write" in names:
            if not _is_approved_safe_write_call(analysis, call):
                violations.append(
                    _violation(
                        "engine-db-safe-write-origin",
                        analysis,
                        call,
                        ast.unparse(call),
                        "safe-write name does not resolve to engine_db_write.safe_engine_db_write",
                        "the reviewed engine_db_write.safe_engine_db_write import",
                    )
                )
            expected = SAFE_ENGINE_WRITE_CALLS.get(key)
            actual = _safe_write_signature(analysis, call)
            if expected != actual:
                violations.append(
                    _violation(
                        "engine-db-new-write-entrypoint",
                        analysis,
                        call,
                        ast.unparse(call),
                        f"safe-write operation/callback {actual!r} does not match reviewed {expected!r}",
                        "an architecture review and an exact SAFE_ENGINE_WRITE_CALLS entry",
                    )
                )

        if "commit" in names and any(
            _looks_like_db_receiver(name) for name in analysis.call_names(call)
        ):
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

        sql_invocation = _sql_invocation(analysis, call)
        if sql_invocation is not None:
            sql_method, sql_node = sql_invocation
            sql = _literal_sql(analysis, sql_node, call)
            exact_candidates = _literal_sql_candidates(
                analysis, sql_node, call
            )
            incomplete = not exact_candidates or any(
                candidate is None for candidate in exact_candidates
            )
            mutation_sql = next(
                (
                    candidate
                    for candidate in exact_candidates
                    if candidate is not None
                    and _sql_write_signature(candidate) is not None
                ),
                None,
            )
            if incomplete and not _is_approved_incomplete_sql(
                analysis, sql_node, call, sql
            ):
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
            reviewed_sql = mutation_sql or sql
            if (
                reviewed_sql is not None
                and _sql_write_signature(reviewed_sql) is not None
            ):
                mutation_counts[key] += 1
                allowed = SQL_MUTATION_ALLOWLIST.get(key)
                if allowed is None or mutation_counts[key] > allowed[0]:
                    violations.append(
                        _violation(
                            "unapproved-persistent-sql",
                            analysis,
                            call,
                            f"{sql_method}({reviewed_sql[:80]!r})",
                            "mutating SQL is outside an exact reviewed persistence symbol",
                            "a safe Engine callback or documented analysis/queue storage function",
                        )
                    )

        if "save" in names:
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

        for writer_name in names & {"write_audio_tags", "write_tags"}:
            writer_key = (analysis.item.path, symbol, writer_name)
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

    for call in analysis.calls():
        writers = {
            writer
            for writer in map(_last_name, analysis.call_names(call))
            if writer in AUDIO_CALLBACK_WRITERS
        }
        if not writers:
            continue
        callback_position = AUDIO_CALLBACK_WRITERS[sorted(writers)[0]]
        if callback_position is None:
            continue
        callback = next(
            (
                keyword.value
                for keyword in call.keywords
                if keyword.arg == "before_save"
            ),
            call.args[callback_position]
            if len(call.args) > callback_position
            else None,
        )
        callback_name = _only_last_name(analysis, callback, call) if callback else ""
        if callback is None or not _callable_provides_verified_backup(
            analysis, callback_name, context=call
        ):
            violations.append(
                _violation(
                    "audio-backup-callback-required",
                    analysis,
                    call,
                    ast.unparse(call),
                    "audio writer callback is absent or cannot reach verified backup creation",
                    "a callback that unconditionally reaches create_verified_audio_backup()",
                )
            )

    return violations


def _definition(
    analysis: _SourceAnalysis, name: str, context: ast.AST | None = None
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    if context is not None:
        binding = analysis._binding(name, context)
        if isinstance(binding, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return binding
    return next(
        (
            node
            for node in ast.walk(analysis.tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ),
        None,
    )


def _definition_symbol(
    analysis: _SourceAnalysis, definition: ast.FunctionDef | ast.AsyncFunctionDef
) -> str:
    parent = analysis.symbol(definition)
    return definition.name if parent == "<module>" else f"{parent}.{definition.name}"


def _callable_provides_verified_backup(
    analysis: _SourceAnalysis,
    name: str,
    seen: frozenset[str] = frozenset(),
    context: ast.AST | None = None,
) -> bool:
    if not name or name in seen:
        return False
    definition = _definition(analysis, name, context)
    if definition is None:
        return name == "create_verified_audio_backup"
    for statement in definition.body:
        call = None
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            call = statement.value
        elif isinstance(statement, ast.Return) and isinstance(statement.value, ast.Call):
            call = statement.value
        if call is not None:
            called = _only_last_name(analysis, call.func, call)
            if called == "create_verified_audio_backup" or _callable_provides_verified_backup(
                analysis, called, seen | {name}, call
            ):
                return True
        if isinstance(statement, (ast.Return, ast.Raise)):
            return False
        if _is_cached_verified_backup_branch(statement):
            calls = [
                node.value
                for node in statement.body
                if isinstance(node, (ast.Assign, ast.AnnAssign))
                and isinstance(node.value, ast.Call)
            ]
            if calls:
                called = _only_last_name(analysis, calls[0].func, calls[0])
                if called == "create_verified_audio_backup" or _callable_provides_verified_backup(
                    analysis, called, seen | {name}, calls[0]
                ):
                    return True
            return False
        if isinstance(
            statement,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.Try,
                ast.With,
                ast.AsyncWith,
                ast.Match,
            ),
        ):
            return False
    return False


def _is_cached_verified_backup_branch(statement: ast.stmt) -> bool:
    if not isinstance(statement, ast.If) or statement.orelse:
        return False
    test = statement.test
    if not (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Is)
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value is None
    ):
        return False
    cache_name = test.left.id
    return any(
        isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == cache_name
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
        )
        and isinstance(node.value, ast.Call)
        for node in statement.body
    )


def _is_verified_backup_callable(
    analysis: _SourceAnalysis, function_name: str, required_call: str, save: ast.Call
) -> bool:
    definition = _definition(analysis, required_call, save)
    if definition is not None:
        return _callable_provides_verified_backup(
            analysis, required_call, context=save
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
        and {
            _last_name(name) for name in analysis.call_names(statement.value)
        }
        == {required_call}
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
            if isinstance(
                safe_statement,
                (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Match),
            ):
                continue
            if _caught_safe_write_failure_can_reach_queue(analysis, safe, queue):
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


def _is_descendant(analysis: _SourceAnalysis, node: ast.AST, ancestor: ast.AST) -> bool:
    current = node
    while current in analysis.parents:
        current = analysis.parents[current]
        if current is ancestor:
            return True
    return False


def _handler_cannot_fall_through(handler: ast.ExceptHandler) -> bool:
    return bool(handler.body) and isinstance(handler.body[-1], (ast.Raise, ast.Return))


def _caught_safe_write_failure_can_reach_queue(
    analysis: _SourceAnalysis, safe: ast.Call, queue: ast.Call
) -> bool:
    current = safe
    while current in analysis.parents:
        current = analysis.parents[current]
        if not isinstance(current, ast.Try) or _is_descendant(analysis, queue, current):
            continue
        if current.handlers and any(
            not _handler_cannot_fall_through(handler) for handler in current.handlers
        ):
            return True
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


def _approved_empty_queue_after_conditional_write(
    analysis: _SourceAnalysis,
    function: str,
    safe_calls: list[ast.Call],
    queue_calls: list[ast.Call],
) -> bool:
    """Allow the reviewed energy batch: no pending rows means an empty queue."""
    if function != "_write_energy_ratings_for_paths" or len(safe_calls) != 1:
        return False
    node = analysis.functions.get(function)
    if node is None or not all(_is_approved_safe_write_call(analysis, call) for call in safe_calls):
        return False
    safe = safe_calls[0]
    guarded_if = next(
        (
            parent
            for parent in _ancestors(analysis, safe)
            if isinstance(parent, ast.If)
            and isinstance(parent.test, ast.Name)
            and parent.test.id == "pending"
        ),
        None,
    )
    if guarded_if is None or guarded_if not in node.body:
        return False
    guard_index = node.body.index(guarded_if)
    empty_changes = any(
        isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "changes" for target in statement.targets)
        and isinstance(statement.value, (ast.List, ast.Tuple))
        and not statement.value.elts
        for statement in node.body[:guard_index]
    )
    assigns_changes_after_safe = any(
        isinstance(child, (ast.Assign, ast.AnnAssign))
        and any(
            any(
                isinstance(part, ast.Name) and part.id == "changes"
                for part in ast.walk(target)
            )
            for target in (child.targets if isinstance(child, ast.Assign) else [child.target])
        )
        and child.lineno > safe.lineno
        for child in ast.walk(guarded_if)
    )
    queues_only_changes = bool(queue_calls) and all(
        any(isinstance(child, ast.Name) and child.id == "changes" for child in ast.walk(queue))
        and queue.lineno > guarded_if.end_lineno
        for queue in queue_calls
    )
    return empty_changes and assigns_changes_after_safe and queues_only_changes


def _ancestors(analysis: _SourceAnalysis, node: ast.AST) -> list[ast.AST]:
    result = []
    current = node
    while current in analysis.parents:
        current = analysis.parents[current]
        result.append(current)
    return result


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
            and analysis.call_names(call) == {POST_COMMIT_QUEUE_ORIGINS[required_call]}
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
            or _approved_empty_queue_after_conditional_write(
                analysis, function, safe_calls, queue_calls
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
    if len(analyses) <= 1:
        return []
    by_path = {analysis.item.path: analysis for analysis in analyses}
    expected_paths = {
        path
        for policy in (
            SQLITE_CONNECT_ALLOWLIST,
            SQL_MUTATION_ALLOWLIST,
            COMMIT_ALLOWLIST,
            AUDIO_SAVE_ALLOWLIST,
            SAFE_ENGINE_WRITE_CALLS,
            DYNAMIC_GETATTR_ALLOWLIST,
            DYNAMIC_SQL_READ_ALLOWLIST,
        )
        for path, _symbol in policy
    }
    expected_paths.update(path for path, _symbol, _attribute in REFLECTIVE_ATTRIBUTE_ALLOWLIST)
    violations: list[Violation] = []
    for path in sorted(expected_paths - by_path.keys()):
        placeholder = _SourceAnalysis(SourceFile(path, ""))
        violations.append(
            _violation(
                "allowlist-expected-file-missing",
                placeholder,
                placeholder.tree,
                path,
                "an expected allowlist source file is absent from the analysis",
                "restore the reviewed source file and rerun the complete production scan",
            )
        )

    observed = {
        "sqlite-connect": Counter(),
        "mutating-sql": Counter(),
        "commit": Counter(),
        "audio-save": Counter(),
        "safe-engine-write": Counter(),
        "dynamic-getattr": Counter(),
        "dynamic-sql-read": Counter(),
        "reflective-attribute": Counter(),
    }
    observed_sql_operations: dict[tuple[str, str], Counter[str]] = {}
    observed_sql_fingerprints: dict[tuple[str, str], Counter[str]] = {}
    for analysis in analyses:
        for node in ast.walk(analysis.tree):
            if isinstance(node, ast.Attribute) and node.attr in REFLECTIVE_ATTRIBUTES:
                observed["reflective-attribute"][(
                    analysis.item.path,
                    analysis.symbol(node),
                    node.attr,
                )] += 1
        for call in analysis.calls():
            names = {_last_name(name) for name in analysis.call_names(call)}
            key = (analysis.item.path, analysis.symbol(call))
            if _is_sqlite_opener_call(analysis, call) and not _is_memory_connect(call):
                observed["sqlite-connect"][key] += 1
            if "commit" in names and any(
                _looks_like_db_receiver(name) for name in analysis.call_names(call)
            ):
                observed["commit"][key] += 1
            sql_invocation = _sql_invocation(analysis, call)
            if sql_invocation is not None:
                _sql_method, sql_node = sql_invocation
                sql = _literal_sql(analysis, sql_node, call)
                exact_candidates = _literal_sql_candidates(
                    analysis, sql_node, call
                )
                if (
                    (
                        not exact_candidates
                        or any(candidate is None for candidate in exact_candidates)
                    )
                    and _expression_fingerprint(analysis, sql_node, call)
                    in DYNAMIC_SQL_READ_ALLOWLIST.get(key, ())
                ):
                    observed["dynamic-sql-read"][key] += 1
                signature = _sql_write_signature(sql) if sql is not None else None
                if signature is not None:
                    observed["mutating-sql"][key] += 1
                    observed_sql_operations.setdefault(key, Counter())[signature] += 1
                    observed_sql_fingerprints.setdefault(key, Counter())[
                        _sql_fingerprint(sql)
                    ] += 1
            if "save" in names:
                observed["audio-save"][key] += 1
            if "safe_engine_db_write" in names and _is_approved_safe_write_call(
                analysis, call
            ):
                observed["safe-engine-write"][key] += 1
            if "getattr" in names and len(call.args) >= 2:
                if _static_string(analysis, call.args[1], call) is None:
                    observed["dynamic-getattr"][key] += 1

    policies = (
        ("sqlite-connect", SQLITE_CONNECT_ALLOWLIST),
        ("mutating-sql", SQL_MUTATION_ALLOWLIST),
        ("commit", COMMIT_ALLOWLIST),
        ("audio-save", AUDIO_SAVE_ALLOWLIST),
        ("dynamic-getattr", DYNAMIC_GETATTR_ALLOWLIST),
        (
            "dynamic-sql-read",
            {
                key: (len(fingerprints), "exact reviewed dynamic read SQL")
                for key, fingerprints in DYNAMIC_SQL_READ_ALLOWLIST.items()
            },
        ),
        ("reflective-attribute", REFLECTIVE_ATTRIBUTE_ALLOWLIST),
    )
    for category, policy in policies:
        for key, (expected, _reason) in policy.items():
            if key[0] not in by_path:
                continue
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
    for key, expected_fingerprints in DYNAMIC_SQL_READ_ALLOWLIST.items():
        if key[0] not in by_path:
            continue
        actual = Counter(
            _expression_fingerprint(by_path[key[0]], sql_node, call)
            for call in by_path[key[0]].calls()
            if by_path[key[0]].symbol(call) == key[1]
            for invocation in [_sql_invocation(by_path[key[0]], call)]
            if invocation is not None
            for _method, sql_node in [invocation]
            if (
                not (
                    candidates := _literal_sql_candidates(
                        by_path[key[0]], sql_node, call
                    )
                )
                or any(candidate is None for candidate in candidates)
            )
            and _expression_fingerprint(by_path[key[0]], sql_node, call)
            in expected_fingerprints
        )
        expected = Counter(expected_fingerprints)
        if actual == expected:
            continue
        analysis = by_path[key[0]]
        violations.append(
            _violation(
                "allowlist-dynamic-sql-fingerprint-mismatch",
                analysis,
                analysis.functions.get(key[1].split(".", 1)[0], analysis.tree),
                f"dynamic read SQL in {key[1]}",
                "the incomplete SQL expression differs from the reviewed AST fingerprints",
                "a fully static SQL expression or an explicit architecture review",
            )
        )
    for key, expected_operations in SQL_OPERATION_ALLOWLIST.items():
        if key[0] not in by_path:
            continue
        actual = observed_sql_operations.get(key, Counter())
        expected = Counter(expected_operations)
        if actual == expected:
            continue
        analysis = by_path[key[0]]
        violations.append(
            _violation(
                "allowlist-operation-mismatch",
                analysis,
                analysis.functions.get(key[1].split(".", 1)[0], analysis.tree),
                f"mutating SQL in {key[1]}",
                f"expected reviewed operations {dict(expected)!r}, found {dict(actual)!r}",
                "an explicit architecture review and exact SQL operation update",
            )
        )
    for key, expected_fingerprints in SQL_FINGERPRINT_ALLOWLIST.items():
        if key[0] not in by_path:
            continue
        actual = observed_sql_fingerprints.get(key, Counter())
        expected = Counter(expected_fingerprints)
        if actual == expected:
            continue
        analysis = by_path[key[0]]
        violations.append(
            _violation(
                "allowlist-sql-fingerprint-mismatch",
                analysis,
                analysis.functions.get(key[1].split(".", 1)[0], analysis.tree),
                f"mutating SQL in {key[1]}",
                "full normalized SQL differs from the reviewed fingerprints",
                "an explicit architecture review and exact SQL fingerprint update",
            )
        )
    for key in SAFE_ENGINE_WRITE_CALLS:
        if key[0] not in by_path:
            continue
        actual = observed["safe-engine-write"][key]
        if actual == 1:
            continue
        analysis = by_path[key[0]]
        violations.append(
            _violation(
                "allowlist-safe-write-mismatch",
                analysis,
                analysis.functions.get(key[1], analysis.tree),
                f"safe_engine_db_write in {key[1]}",
                f"policy expects exactly one reviewed safe-write call, found {actual}",
                "the reviewed safe_engine_db_write operation/callback pair",
            )
        )
    return violations


def analyze_sources(items: list[SourceFile]) -> list[Violation]:
    violations = []
    analyses = [_SourceAnalysis(item) for item in items]
    for analysis in analyses:
        violations.extend(_check_capability_policy(analysis))
        violations.extend(_check_calls(analysis))
        violations.extend(_check_post_commit(analysis))
        violations.extend(_check_startup(analysis))
    violations.extend(_check_exact_allowlists(analyses))
    return sorted(violations, key=lambda item: (item.path, item.line, item.rule))


def format_violations(violations: list[Violation]) -> str:
    return "\n".join(str(item) for item in violations)
