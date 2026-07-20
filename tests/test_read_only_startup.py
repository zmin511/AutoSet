import ast
import io
import json
from pathlib import Path

import set_app.set_app as set_app


PROJECT_DIR = Path(__file__).resolve().parents[1]
STARTUP_REFRESH_STATUS = "disabled; use manual refresh"


class _FakeSocket:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def settimeout(self, _timeout):
        pass

    def connect_ex(self, _address):
        return 1


class _FakeServer:
    def __init__(self, address, handler):
        self.address = address
        self.handler = handler
        self.serve_calls = 0

    def serve_forever(self):
        self.serve_calls += 1


class _FakeTimer:
    instances = []

    def __init__(self, interval, function):
        self.interval = interval
        self.function = function
        self.started = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True


def test_main_is_read_only_except_for_preserved_startup_analysis(tmp_path, monkeypatch):
    music_root = tmp_path / "Music"
    music_root.mkdir()
    audio_path = music_root / "untouched.mp3"
    audio_contents = b"synthetic audio sentinel"
    audio_path.write_bytes(audio_contents)
    db_path = tmp_path / "Engine Library" / "Database2" / "m.db"
    builder = tmp_path / "tools" / "engine_set_builder.py"
    reports = tmp_path / "reports"
    tag_backups = tmp_path / "tag_backups"

    servers = []
    analysis_calls = []
    tag_calls = []
    genre_calls = []
    subprocess_calls = []
    db_calls = []
    browser_calls = []
    audio_file_calls = []
    original_path_open = Path.open

    def fake_server(address, handler):
        server = _FakeServer(address, handler)
        servers.append(server)
        return server

    def unexpected_thread(*args, **kwargs):
        raise AssertionError(f"startup must not create Thread: {args!r} {kwargs!r}")

    def unexpected_db_connect(*args, **kwargs):
        db_calls.append((args, kwargs))
        raise AssertionError("startup must not open Engine DJ DB for tag refresh")

    def unexpected_subprocess(*args, **kwargs):
        subprocess_calls.append((args, kwargs))
        raise AssertionError("startup must not run tag refresh subprocesses")

    def unexpected_refresh_tags(*args, **kwargs):
        tag_calls.append((args, kwargs))
        raise AssertionError("startup must not call refresh_tags")

    def unexpected_refresh_genres(*args, **kwargs):
        genre_calls.append((args, kwargs))
        raise AssertionError("startup must not call refresh_genres")

    def guard_audio_file(path, *args, **kwargs):
        if path == audio_path:
            audio_file_calls.append((args, kwargs))
            raise AssertionError("startup must not read or write audio files")
        return original_path_open(path, *args, **kwargs)

    _FakeTimer.instances = []
    monkeypatch.setattr(set_app, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(set_app, "MUSIC_ROOT", music_root)
    monkeypatch.setattr(set_app, "DB_PATH", db_path)
    monkeypatch.setattr(set_app, "BUILDER", builder)
    monkeypatch.setattr(set_app.socket, "socket", lambda *_args, **_kwargs: _FakeSocket())
    monkeypatch.setattr(set_app, "ThreadingHTTPServer", fake_server)
    monkeypatch.setattr(set_app.threading, "Thread", unexpected_thread)
    monkeypatch.setattr(set_app.threading, "Timer", _FakeTimer)
    monkeypatch.setattr(
        set_app,
        "start_analysis_job",
        lambda mode: analysis_calls.append(mode),
    )
    monkeypatch.setattr(set_app, "refresh_tags", unexpected_refresh_tags)
    monkeypatch.setattr(set_app, "refresh_genres", unexpected_refresh_genres)
    monkeypatch.setattr(set_app.subprocess, "run", unexpected_subprocess)
    monkeypatch.setattr(set_app.sqlite3, "connect", unexpected_db_connect)
    monkeypatch.setattr(Path, "open", guard_audio_file)
    monkeypatch.setattr(
        set_app.webbrowser,
        "open",
        lambda url: browser_calls.append(url),
    )

    set_app.main()

    assert analysis_calls == ["startup"]
    assert tag_calls == []
    assert genre_calls == []
    assert subprocess_calls == []
    assert db_calls == []
    assert audio_file_calls == []
    assert len(servers) == 1
    assert servers[0].address == ("127.0.0.1", 8765)
    assert servers[0].handler is set_app.Handler
    assert servers[0].serve_calls == 1
    assert len(_FakeTimer.instances) == 1
    assert _FakeTimer.instances[0].interval == 0.8
    assert _FakeTimer.instances[0].started is True
    assert browser_calls == []
    assert not reports.exists()
    assert not tag_backups.exists()
    with original_path_open(audio_path, "rb") as audio_file:
        assert audio_file.read() == audio_contents
    assert set_app.APP_STATE["startup_refresh"] == STARTUP_REFRESH_STATUS


def test_main_has_no_automatic_startup_refresh_target():
    source_path = PROJECT_DIR / "set_app" / "set_app.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    main_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )

    main_names = {
        node.id
        for node in ast.walk(main_node)
        if isinstance(node, ast.Name)
    }

    assert "startup_refresh_new" not in main_names
    assert "refresh_tags" not in main_names
    assert "refresh_genres" not in main_names
    assert not hasattr(set_app, "startup_refresh_new")


def test_startup_refresh_status_is_stable_and_disabled():
    status = set_app.APP_STATE["startup_refresh"]

    assert status == STARTUP_REFRESH_STATUS
    assert "waiting" not in status.casefold()
    assert "refreshing" not in status.casefold()


def test_config_api_keeps_startup_refresh_field(tmp_path, monkeypatch):
    monkeypatch.setattr(set_app, "SSD_ROOT", tmp_path / "ssd")
    monkeypatch.setattr(set_app, "MUSIC_ROOT", tmp_path / "Music")
    monkeypatch.setattr(set_app, "SETS_DIR", tmp_path / "Sets")
    monkeypatch.setattr(set_app, "DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr(set_app, "CONFIG_PATH", tmp_path / "paths.json")
    monkeypatch.setattr(set_app, "BUILDER", tmp_path / "engine_set_builder.py")
    monkeypatch.setitem(
        set_app.APP_STATE,
        "startup_refresh",
        STARTUP_REFRESH_STATUS,
    )
    sent = []
    handler = object.__new__(set_app.Handler)
    handler.path = "/api/config"
    monkeypatch.setattr(
        set_app.Handler,
        "send_json",
        lambda _self, data, status=200: sent.append((data, status)),
    )

    handler.do_GET()

    assert len(sent) == 1
    payload, status = sent[0]
    assert status == 200
    assert payload["startup_refresh"] == STARTUP_REFRESH_STATUS


def test_manual_refresh_tags_endpoint_contract_is_unchanged(monkeypatch):
    expected = {"ok": False, "code": 7, "output": "synthetic output"}
    payload = json.dumps({"path": "Manual Folder"}).encode("utf-8")
    refresh_calls = []
    sent = []
    handler = object.__new__(set_app.Handler)
    handler.path = "/api/refresh-tags"
    handler.headers = {"Content-Length": str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    monkeypatch.setattr(
        set_app,
        "refresh_tags",
        lambda rel: refresh_calls.append(rel) or expected,
    )
    monkeypatch.setattr(
        set_app.Handler,
        "send_json",
        lambda _self, data, status=200: sent.append((data, status)),
    )

    handler.do_POST()

    assert refresh_calls == ["Manual Folder"]
    assert sent == [(expected, 200)]
