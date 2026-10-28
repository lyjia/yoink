import pytest

from yoink import overrides
from yoink.overrides import load_rules, match, normalize_domain, rule_argv, save_rules

RULES = {"youtube.com": {}, "m.youtube.com": {}, "example.org": {}}


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("youtube.com", "youtube.com"),
        ("www.youtube.com", "youtube.com"),
        ("notyoutube.com", None),
        ("m.youtube.com", "m.youtube.com"),
        ("a.m.youtube.com", "m.youtube.com"),
        ("WWW.YouTube.COM", "youtube.com"),
        ("example.com", None),
        (None, None),
        ("", None),
    ],
)
def test_match(host, expected):
    assert match(host, RULES) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [(" www.YouTube.com. ", "youtube.com"), (".m.youtube.com", "m.youtube.com"), ("WWW.", "www")],
)
def test_normalize_domain(text, expected):
    assert normalize_domain(text) == expected


def test_load_missing_file(tmp_path):
    assert load_rules(tmp_path / "overrides.json") == {}


@pytest.mark.parametrize("text", ["{not json", "[1, 2]", ""])
def test_load_malformed_file(tmp_path, caplog, text):
    path = tmp_path / "overrides.json"
    path.write_text(text, encoding="utf-8")
    assert load_rules(path) == {}
    assert "Ignoring" in caplog.text


def test_save_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("YOINK_SETTINGS_DIR", str(tmp_path / "sandbox"))
    path = overrides.rules_path()
    assert path == tmp_path / "sandbox" / "overrides.json"
    rules = {"youtube.com": {"--paths": "D:/video/yt", "--embed-subs": True}}
    save_rules(path, rules)
    assert load_rules(path) == rules


def test_rule_argv():
    options = {"--paths": "D:/v", "--output": "", "--embed-subs": True, "--write-subs": False}
    assert rule_argv(options) == ["--paths", "D:/v", "--embed-subs"]
