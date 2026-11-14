"""The pieces of cli.py that don't need a window."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ccdiscuss import cli


def test_read_jsonl_leaves_a_partial_line_for_next_time(tmp_path):
    path = tmp_path / "out.jsonl"
    path.write_text('{"n": 1}\n{"n": 2}\n{"n": ', encoding="utf-8")
    records, offset = cli.read_jsonl(path)
    assert [r["n"] for r in records] == [1, 2]

    with path.open("a", encoding="utf-8") as f:
        f.write('3}\n')
    records, _ = cli.read_jsonl(path, offset)
    assert [r["n"] for r in records] == [3]


def test_append_jsonl_round_trips_non_ascii(tmp_path):
    path = tmp_path / "box.jsonl"
    path.touch()
    cli.append_jsonl(path, {"text": "⛰️ »x« café"})
    records, _ = cli.read_jsonl(path)
    assert records == [{"text": "⛰️ »x« café"}]


@pytest.mark.parametrize(
    "name, lang",
    [("notes.md", None), ("README.markdown", None), ("app.py", "py"), ("Makefile", "makefile")],
)
def test_read_source_picks_how_to_show_a_file(tmp_path, name, lang):
    path = tmp_path / name
    path.write_text("hé ⛰️\n", encoding="utf-8")
    text, source = cli.read_source(path)
    assert text == "hé ⛰️\n"
    assert source == {"path": str(path.resolve()), "lang": lang}


def test_read_source_rejects_binary(tmp_path):
    path = tmp_path / "blob.bin"
    path.write_bytes(b"\xff\xfe\x00\x81")
    with pytest.raises(SystemExit, match="not a text file"):
        cli.read_source(path)


def test_read_source_rejects_missing_and_huge(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="not a file"):
        cli.read_source(tmp_path / "missing.md")
    big = tmp_path / "big.md"
    big.write_text("x" * 20, encoding="utf-8")
    monkeypatch.setattr(cli, "MAX_FILE_BYTES", 10)
    with pytest.raises(SystemExit, match="too big"):
        cli.read_source(big)


def test_quoted_comment():
    c = {"quote": "line one\nline two", "text": "my thought", "lines": "3-4", "context": "…a »b« c…"}
    assert cli.quoted(c) == "> line one\n> line two\n[lines 3-4]\n[context: …a »b« c…]\nmy thought"


def test_shell_path_uses_forward_slashes_and_quotes_spaces():
    out = cli.shell_path(Path("/tmp/with space/ccdiscuss-1"))
    assert "\\" not in out
    assert out == "'/tmp/with space/ccdiscuss-1'"


def test_pid_alive(tmp_path):
    pid_file = tmp_path / "x.pid"
    pid_file.write_text(str(os.getpid()))
    assert cli.pid_alive(pid_file)

    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    pid_file.write_text(str(done.pid))
    assert not cli.pid_alive(pid_file)

    pid_file.write_text("not a pid")
    assert not cli.pid_alive(pid_file)
    assert not cli.pid_alive(tmp_path / "missing.pid")
