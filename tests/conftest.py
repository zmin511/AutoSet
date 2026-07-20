from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_audio_tag_retry_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Keep every test away from the application's persistent runtime queue."""
    from set_app import set_app

    monkeypatch.setattr(
        set_app,
        "AUDIO_TAG_RETRY_QUEUE_PATH",
        tmp_path / "runtime" / "audio_tag_retry.sqlite3",
    )
