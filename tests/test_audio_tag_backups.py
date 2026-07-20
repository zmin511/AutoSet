from pathlib import Path
from types import SimpleNamespace

import pytest
from mutagen.id3 import ID3

from set_app import set_app

import audio_tag_backup
import engine_write_tags
import review_new_genres


def _backup_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


def _decision() -> review_new_genres.Decision:
    return review_new_genres.Decision(
        genre="House",
        family="House",
        style="Deep House",
        set_ok=True,
        stem_type="full",
        energy=3,
        confidence="high",
        reason="synthetic",
    )


def test_verified_backup_is_collision_safe_and_preserves_relative_special_path(tmp_path):
    music_root = tmp_path / "Music library ü #&"
    source = music_root / "Artist name" / "set [one]" / "трек #1.mp3"
    source.parent.mkdir(parents=True)
    original = b"synthetic audio contents"
    source.write_bytes(original)
    backup_dir = tmp_path / "Backups with spaces"

    first = audio_tag_backup.create_verified_audio_backup(
        source, backup_dir, music_root
    )
    second = audio_tag_backup.create_verified_audio_backup(
        source, backup_dir, music_root
    )

    assert first != second
    assert first.suffix == source.suffix
    assert first.read_bytes() == original
    assert second.read_bytes() == original
    assert Path("Artist name/set [one]/трек #1.mp3").parts == first.parts[-3:]


def test_write_audio_tags_backs_up_original_before_save(tmp_path, monkeypatch):
    music_root = tmp_path / "Music"
    source = music_root / "Artist" / "track.mp3"
    source.parent.mkdir(parents=True)
    original = b"original synthetic audio"
    source.write_bytes(original)
    backup_dir = tmp_path / "tag_backups"
    events = []

    real_backup = engine_write_tags.create_verified_audio_backup
    real_save = ID3.save

    def record_backup(*args, **kwargs):
        backup = real_backup(*args, **kwargs)
        assert backup.read_bytes() == original
        events.append("backup")
        return backup

    def record_save(self, *args, **kwargs):
        events.append("save")
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(engine_write_tags, "create_verified_audio_backup", record_backup)
    monkeypatch.setattr(ID3, "save", record_save)

    result = engine_write_tags.write_audio_tags(
        source,
        genre="House",
        backup_dir=backup_dir,
        music_root=music_root,
    )

    assert result.ok is True
    assert events == ["backup", "save"]
    backups = _backup_files(backup_dir)
    assert len(backups) == 1
    assert backups[0].read_bytes() == original


def test_backup_failure_prevents_audio_tag_save(tmp_path, monkeypatch):
    source = tmp_path / "Music" / "track.mp3"
    source.parent.mkdir()
    original = b"untouched synthetic audio"
    source.write_bytes(original)
    saves = []

    def fail_backup(*_args, **_kwargs):
        raise audio_tag_backup.AudioTagBackupError("synthetic backup failure")

    monkeypatch.setattr(engine_write_tags, "create_verified_audio_backup", fail_backup)
    monkeypatch.setattr(ID3, "save", lambda *_args, **_kwargs: saves.append(True))

    result = engine_write_tags.write_audio_tags(source, genre="House")

    assert result.ok is False
    assert "synthetic backup failure" in str(result.file_tags_warning)
    assert saves == []
    assert source.read_bytes() == original


def test_dry_run_no_change_and_unsupported_format_create_no_backup(tmp_path):
    music_root = tmp_path / "Music"
    music_root.mkdir()
    source = music_root / "track.mp3"
    source.write_bytes(b"synthetic audio")

    dry_backups = tmp_path / "dry_backups"
    dry_result = engine_write_tags.write_audio_tags(
        source,
        genre="House",
        dry_run=True,
        backup_dir=dry_backups,
        music_root=music_root,
    )
    assert dry_result.ok is True
    assert not dry_backups.exists()

    initial_backups = tmp_path / "initial_backups"
    first_result = engine_write_tags.write_audio_tags(
        source,
        genre="House",
        rating=4,
        backup_dir=initial_backups,
        music_root=music_root,
    )
    assert first_result.ok is True

    no_change_backups = tmp_path / "no_change_backups"
    no_change_result = engine_write_tags.write_audio_tags(
        source,
        genre="House",
        rating=4,
        backup_dir=no_change_backups,
        music_root=music_root,
    )
    assert no_change_result.ok is True
    assert no_change_result.file_tags_updated is False
    assert not no_change_backups.exists()

    unsupported = music_root / "track.wav"
    unsupported.write_bytes(b"synthetic wav")
    unsupported_backups = tmp_path / "unsupported_backups"
    unsupported_result = engine_write_tags.write_audio_tags(
        unsupported,
        genre="House",
        backup_dir=unsupported_backups,
        music_root=music_root,
    )
    assert unsupported_result.ok is False
    assert not unsupported_backups.exists()


def test_review_batch_continues_after_one_backup_failure(tmp_path, monkeypatch):
    music_root = tmp_path / "Music"
    music_root.mkdir()
    failed = music_root / "01 failed.mp3"
    successful = music_root / "02 успешный #.mp3"
    failed_original = b"failed file original"
    successful_original = b"successful file original"
    failed.write_bytes(failed_original)
    successful.write_bytes(successful_original)
    backup_dir = tmp_path / "Backups"
    real_backup = review_new_genres.create_verified_audio_backup

    def mixed_backup(file_path, *args, **kwargs):
        if Path(file_path) == failed:
            raise audio_tag_backup.AudioTagBackupError("synthetic first-file failure")
        return real_backup(file_path, *args, **kwargs)

    monkeypatch.setattr(review_new_genres, "create_verified_audio_backup", mixed_backup)
    monkeypatch.setattr(review_new_genres, "load_engine_index", lambda _path: {})
    monkeypatch.setattr(
        review_new_genres, "audio_files", lambda _target: [failed, successful]
    )
    monkeypatch.setattr(review_new_genres, "decide", lambda *_args: _decision())

    code = review_new_genres.main(
        [
            str(music_root),
            "--apply",
            "--db-path",
            str(tmp_path / "synthetic.db"),
            "--music-root",
            str(music_root),
            "--report-dir",
            str(tmp_path / "reports"),
            "--backup-dir",
            str(backup_dir),
        ]
    )

    assert code == 1
    assert failed.read_bytes() == failed_original
    assert ID3(str(successful)).get("TCON").text == ["House"]
    backups = _backup_files(backup_dir)
    assert len(backups) == 1
    assert backups[0].read_bytes() == successful_original


def test_refresh_commands_cannot_disable_backups(tmp_path, monkeypatch):
    music_root = tmp_path / "Music"
    target = music_root / "New"
    target.mkdir(parents=True)
    commands = []

    monkeypatch.setattr(set_app, "MUSIC_ROOT", music_root)
    monkeypatch.setattr(set_app, "DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr(
        set_app.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command)
        or SimpleNamespace(returncode=0, stdout="ok"),
    )

    assert set_app.refresh_tags("New")["ok"] is True
    assert "--backup-files" in commands[-1]
    assert "--apply" in commands[-1]

    assert set_app.refresh_genres("New")["ok"] is True
    assert "--apply" in commands[-1]
    assert "--no-backup" not in commands[-1]


def test_review_cli_rejects_removed_no_backup_option(tmp_path):
    with pytest.raises(SystemExit) as exc_info:
        review_new_genres.main([str(tmp_path), "--apply", "--no-backup"])

    assert exc_info.value.code == 2
