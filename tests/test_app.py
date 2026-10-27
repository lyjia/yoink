from pathlib import Path

from yoink import app


def ini(tmp_path, monkeypatch):
    monkeypatch.setenv("YOINK_SETTINGS_DIR", str(tmp_path))
    return app.settings()


def test_settings_dir_redirects_to_ini(tmp_path, monkeypatch):
    s = ini(tmp_path, monkeypatch)
    s.setValue(app.KEY_COOKIES, "none")
    s.sync()
    assert Path(s.fileName()) == tmp_path / "yoink.ini"
    assert "cookies=none" in (tmp_path / "yoink.ini").read_text()


def test_last_dir_migrates_once(tmp_path, monkeypatch):
    s = ini(tmp_path, monkeypatch)
    s.setValue("main/last_dir", "/tmp/old")
    app.migrate_settings(s)
    assert s.value(app.KEY_DIR) == "/tmp/old"
    assert not s.contains("main/last_dir")
    # A later stray last_dir never overwrites the current value.
    s.setValue("main/last_dir", "/tmp/stale")
    app.migrate_settings(s)
    assert s.value(app.KEY_DIR) == "/tmp/old"
    assert not s.contains("main/last_dir")


def test_migration_without_last_dir_is_a_no_op(tmp_path, monkeypatch):
    s = ini(tmp_path, monkeypatch)
    app.migrate_settings(s)
    assert not s.contains(app.KEY_DIR)
