"""`ccdiscuss watch` and `ccdiscuss reply` run as real processes, as the
Monitor tool and Bash run them, with a stand-in for the window."""

import json
import subprocess
import sys
import time

import pytest

TIMEOUT = 30


def ccdiscuss(*args, **kw):
    return subprocess.run(
        [sys.executable, "-c", "from ccdiscuss.cli import main; main()", *args],
        capture_output=True, timeout=TIMEOUT, **kw,
    )


def write_jsonl(path, *records):
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


@pytest.fixture
def window():
    """A process standing in for the discussion window."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield proc
    proc.kill()
    proc.wait()


@pytest.fixture
def discussion(tmp_path, window):
    d = tmp_path / "ccdiscuss-test"
    d.mkdir()
    (d / "outbox.jsonl").touch()
    (d / "inbox.jsonl").touch()
    (d / "window.pid").write_text(str(window.pid))
    return d


def comment(thread, quote, text, ts):
    return {"type": "comment", "thread": thread, "quote": quote, "context": None,
            "lines": None, "text": text, "ts": ts}


def test_watch_prints_comments_and_batch_then_cleans_up(discussion):
    write_jsonl(
        discussion / "outbox.jsonl",
        comment("t1", "a passage", "first ⛰️", 1.0),
        {"type": "batch", "items": [comment("t2", "other", "staged »note«", 2.0)], "ts": 3.0},
        {"type": "closed", "ts": 4.0},
    )
    out = ccdiscuss("watch", str(discussion))
    stdout = out.stdout.decode("utf-8")

    assert out.returncode == 0, out.stderr
    assert "[ccdiscuss comment, thread t1]\n> a passage\nfirst ⛰️" in stdout
    assert "[ccdiscuss staged comments: answer in the terminal, not in threads]" in stdout
    assert "> other\nstaged »note«" in stdout
    assert stdout.rstrip().endswith("[ccdiscuss closed] the discussion window was closed")
    assert "\\" not in stdout.split("[reply: ccdiscuss reply ")[1].split(" t1 ")[0]
    assert not discussion.exists()


def test_watch_does_not_resend_answered_comments(discussion):
    write_jsonl(
        discussion / "outbox.jsonl",
        comment("t1", "answered", "ALREADY-ANSWERED", 1.0),
        comment("t2", "unanswered", "STILL-WAITING", 2.0),
        {"type": "closed", "ts": 5.0},
    )
    write_jsonl(discussion / "inbox.jsonl", {"type": "reply", "thread": "t1", "text": "done", "ts": 1.5})
    stdout = ccdiscuss("watch", str(discussion)).stdout.decode("utf-8")
    assert "STILL-WAITING" in stdout
    assert "ALREADY-ANSWERED" not in stdout


def test_watch_ends_when_the_window_process_is_gone(discussion, window):
    window.kill()
    window.wait()
    out = ccdiscuss("watch", str(discussion))
    assert "[ccdiscuss closed]" in out.stdout.decode("utf-8")


def test_watch_on_a_finished_discussion(tmp_path):
    out = ccdiscuss("watch", str(tmp_path / "gone"))
    assert "already over" in out.stdout.decode("utf-8")


def test_watch_streams_a_comment_written_while_running(discussion):
    watch = subprocess.Popen(
        [sys.executable, "-c", "from ccdiscuss.cli import main; main()", "watch", str(discussion)],
        stdout=subprocess.PIPE,
    )
    try:
        time.sleep(1)
        write_jsonl(discussion / "outbox.jsonl", comment("t1", "live", "hello ⛰️", time.time()))
        assert watch.stdout.readline().decode("utf-8").strip() == "[ccdiscuss comment, thread t1]"
        write_jsonl(discussion / "outbox.jsonl", {"type": "closed", "ts": time.time()})
        # Read through the same buffered reader as readline above; communicate()
        # on POSIX reads the pipe directly and would miss what's already buffered.
        rest = watch.stdout.read().decode("utf-8")
        watch.wait(timeout=TIMEOUT)
        assert "hello ⛰️" in rest
        assert "[ccdiscuss closed]" in rest
    finally:
        watch.kill()


def test_reply_appends_utf8_markdown(discussion):
    out = ccdiscuss("reply", str(discussion), "t3", input="Noted ⛰️ »ok«\n".encode("utf-8"))
    assert out.returncode == 0, out.stderr
    record = json.loads((discussion / "inbox.jsonl").read_text(encoding="utf-8"))
    assert record["thread"] == "t3"
    assert record["text"] == "Noted ⛰️ »ok«"


def test_reply_refuses_empty_text_and_closed_windows(discussion, tmp_path):
    assert ccdiscuss("reply", str(discussion), "t1", input=b"  \n").returncode != 0
    assert ccdiscuss("reply", str(tmp_path / "gone"), "t1", input=b"hi").returncode != 0
