"""Picking the response to discuss out of a Claude Code transcript."""

import json

import pytest

from ccdiscuss import transcript


def prompt(text):
    return {"type": "user", "origin": {"kind": "human"}, "message": {"content": text}}


def discuss():
    return {"type": "user", "message": {"content": "<command-name>/discuss</command-name>"}}


def notification(text):
    """A background event (e.g. a Monitor line) that starts a turn on its own."""
    return {"type": "user", "message": {"content": text}}


def say(*blocks):
    return {"type": "assistant", "message": {"content": list(blocks)}}


def text(t):
    return {"type": "text", "text": t}


def tool_call():
    return say({"type": "tool_use", "id": "x", "name": "Bash", "input": {}})


def tool_result():
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}}


def write(tmp_path, rows, tail=""):
    path = tmp_path / "session.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.write(tail)
    return path


def test_last_response_before_discuss(tmp_path):
    path = write(tmp_path, [prompt("question"), say(text("the answer")), discuss()])
    assert transcript.last_response(path) == "the answer"


def test_only_text_after_the_last_tool_call(tmp_path):
    rows = [
        prompt("question"),
        say(text("let me look")),
        tool_call(),
        tool_result(),
        say(text("part one")),
        say(text("part two")),
        discuss(),
    ]
    assert transcript.last_response(write(tmp_path, rows)) == "part one\n\npart two"


def test_thinking_does_not_split_the_final_text(tmp_path):
    rows = [
        prompt("question"),
        tool_call(),
        tool_result(),
        say(text("before"), {"type": "thinking", "thinking": "hmm"}, text("after")),
        discuss(),
    ]
    assert transcript.last_response(write(tmp_path, rows)) == "before\n\nafter"


def test_skips_turns_from_an_earlier_discussion(tmp_path):
    rows = [
        prompt("question"),
        say(text("the real answer")),
        discuss(),
        tool_call(),
        tool_result(),
        say(text("The discussion window is open.")),
        notification("<task-notification>discuss comments: [ccdiscuss comment, thread t1]</task-notification>"),
        tool_call(),
        tool_result(),
        say(text("Replied in thread t1.")),
        discuss(),
    ]
    assert transcript.last_response(write(tmp_path, rows)) == "the real answer"


def test_answer_to_staged_comments_is_a_real_response(tmp_path):
    rows = [
        prompt("question"),
        say(text("first answer")),
        discuss(),
        say(text("The discussion window is open.")),
        notification("discuss comments: [ccdiscuss staged comments: answer in the terminal, not in threads]"),
        say(text("answer to the staged comments")),
        discuss(),
    ]
    assert transcript.last_response(write(tmp_path, rows)) == "answer to the staged comments"


def test_ignores_sidechains_and_a_half_written_last_line(tmp_path):
    rows = [
        prompt("question"),
        say(text("main answer")),
        {**say(text("subagent chatter")), "isSidechain": True},
        discuss(),
    ]
    path = write(tmp_path, rows, tail='{"type": "assistant", "mess')
    assert transcript.last_response(path) == "main answer"


def test_non_ascii_text_reads_as_utf8(tmp_path):
    path = write(tmp_path, [prompt("q"), say(text("café ⛰️ »quote«")), discuss()])
    assert transcript.last_response(path) == "café ⛰️ »quote«"


def test_transcript_path_finds_the_newest_match(tmp_path, monkeypatch):
    monkeypatch.setattr(transcript, "PROJECTS_DIR", tmp_path)
    (tmp_path / "proj").mkdir()
    found = tmp_path / "proj" / "abc.jsonl"
    found.write_text("", encoding="utf-8")
    assert transcript.transcript_path("abc") == found


def test_transcript_path_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(transcript, "PROJECTS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        transcript.transcript_path("nope")
