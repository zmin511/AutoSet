import re
from pathlib import Path

from set_app.set_app import APP_VERSION


PROJECT_DIR = Path(__file__).resolve().parents[1]


def test_release_version_is_consistent():
    version = (PROJECT_DIR / "VERSION").read_text(encoding="utf-8").strip()

    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert APP_VERSION == version
    assert f"Version: `{version}`" in (
        PROJECT_DIR / "README.md"
    ).read_text(encoding="utf-8")
    assert f"Версия: `{version}`" in (
        PROJECT_DIR / "README_RU.md"
    ).read_text(encoding="utf-8")
    assert f"Version: `{version}`" in (
        PROJECT_DIR / "README_EN.md"
    ).read_text(encoding="utf-8")

    changelog = (PROJECT_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
    release_entries = re.findall(r"^## (\d+\.\d+\.\d+)$", changelog, re.MULTILINE)
    assert release_entries
    assert release_entries[0] == version

    index_html = (PROJECT_DIR / "set_app" / "index.html").read_text(
        encoding="utf-8"
    )
    assets = re.findall(
        r"(?:href|src)=\"/static/([^\"?]+\.(?:css|js))\?v=([^\"]+)\"",
        index_html,
    )
    assert assets
    assert {asset_version for _, asset_version in assets} == {version}

    referenced_js = {name for name, _ in assets if name.endswith(".js")}
    current_js = {
        path.name
        for path in (PROJECT_DIR / "set_app" / "static").glob("*.js")
    }
    assert referenced_js == current_js
