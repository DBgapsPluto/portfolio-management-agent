import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from tradingagents.observability.run_archive import (
    archive_metadata, archive_report, archive_wrap_node, resolve_run_dir,
)


class _Sample(BaseModel):
    name: str
    score: float
    items: list[str]


def test_archive_pydantic_report(tmp_path):
    sample = _Sample(name="goldilocks", score=0.42, items=["a", "b"])
    path = archive_report("2026-05-18", "research_decision", sample, base=tmp_path)
    assert path is not None
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["name"] == "goldilocks"
    assert data["score"] == 0.42


def test_archive_dict_report(tmp_path):
    payload = {"k1": 1, "k2": [1, 2, 3], "nested": {"x": "y"}}
    path = archive_report("2026-05-18", "data", payload, base=tmp_path)
    assert path is not None
    data = json.loads(path.read_text())
    assert data["k1"] == 1
    assert data["nested"]["x"] == "y"


def test_archive_string_report(tmp_path):
    path = archive_report("2026-05-18", "summary", "hello world", base=tmp_path)
    assert path.exists()
    assert path.read_text(encoding="utf-8").strip('"\n') == "hello world"


def test_archive_none_returns_none(tmp_path):
    assert archive_report("2026-05-18", "x", None, base=tmp_path) is None


def test_archive_metadata_writes_file(tmp_path):
    archive_metadata("2026-05-18", {"preset": "db_gaps", "capital_krw": 100}, base=tmp_path)
    md = json.loads((tmp_path / "2026-05-18" / "metadata.json").read_text())
    assert md["preset"] == "db_gaps"
    assert md["as_of_date"] == "2026-05-18"


def test_archive_wrap_node_saves_keys(tmp_path, monkeypatch):
    # 임시 디렉토리를 base로 강제하기 위해 resolve_run_dir 직접 mock
    monkeypatch.setattr(
        "tradingagents.observability.run_archive.resolve_run_dir",
        lambda as_of, base=None: (tmp_path / as_of, tmp_path / as_of)[0].__truediv__("").parent.__class__(tmp_path / as_of),
    )

    # 더 단순: archive_report 자체를 spy로 monkey patch
    saved = {}

    def fake_archive(as_of_date, key, payload, base=None):
        saved.setdefault(as_of_date, {})[key] = payload
        return Path("/tmp/fake")

    monkeypatch.setattr(
        "tradingagents.observability.run_archive.archive_report",
        fake_archive,
    )

    def fake_node(state):
        return {
            "foo_report": {"value": 42},
            "foo_summary": "summary text",
            "unrelated": "skip me",
        }

    wrapped = archive_wrap_node(fake_node, ["foo_report", "foo_summary"])
    result = wrapped({"as_of_date": "2026-05-18"})

    assert result["foo_report"] == {"value": 42}
    assert "2026-05-18" in saved
    assert "foo_report" in saved["2026-05-18"]
    assert "foo_summary" in saved["2026-05-18"]
    assert "unrelated" not in saved["2026-05-18"]


def test_resolve_run_dir_creates_directory(tmp_path):
    d = resolve_run_dir("2026-05-18", base=tmp_path)
    assert d.exists()
    assert d.name == "2026-05-18"
