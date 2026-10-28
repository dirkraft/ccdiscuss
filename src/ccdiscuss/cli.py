"""ccdiscuss: comment on parts of a Claude Code response in its own window.

A discussion is a temp directory shared by the window and the session:

    response.md    the text being discussed
    outbox.jsonl   window -> session: comments, then a final "closed"
    inbox.jsonl    session -> window: replies
    window.pid     the window process

  ccdiscuss open <session-id>      extract the response, launch the window, print the dir
  ccdiscuss watch <dir>            one stdout event per comment, for the Monitor tool
  ccdiscuss reply <dir> <thread>   post stdin (markdown) as a reply in a thread
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import transcript

POLL_SECONDS = 0.5


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def read_jsonl(path: Path, offset: int = 0) -> tuple[list[dict], int]:
    """Complete records from byte `offset` on, and the offset to resume from."""
    with path.open("rb") as f:
        f.seek(offset)
        data = f.read()
    end = data.rfind(b"\n") + 1  # leave a partially written line for next time
    records = [json.loads(line) for line in data[:end].splitlines() if line.strip()]
    return records, offset + end


def cmd_open(args) -> None:
    try:
        text = transcript.last_response(transcript.transcript_path(args.session_id))
    except FileNotFoundError as e:
        sys.exit(str(e))
    if not text.strip():
        sys.exit("no response text found before this prompt")

    d = Path(tempfile.mkdtemp(prefix="ccdiscuss-"))
    (d / "response.md").write_text(text)
    (d / "outbox.jsonl").touch()
    (d / "inbox.jsonl").touch()
    with (d / "window.log").open("w") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "ccdiscuss.window", str(d)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
        )
    (d / "window.pid").write_text(str(proc.pid))
    print(d)


def _window_alive(d: Path) -> bool:
    try:
        os.kill(int((d / "window.pid").read_text()), 0)
    except (OSError, ValueError):
        return False
    return True


def format_comment(d: Path, c: dict) -> str:
    quote = "\n".join("> " + line for line in c["quote"].splitlines())
    return (
        f"[ccdiscuss comment, thread {c['thread']}]\n"
        f"{quote}\n"
        f"{c['text']}\n"
        f"[reply: ccdiscuss reply {d} {c['thread']} <<'EOF' ... EOF]"
    )


def cmd_watch(args) -> None:
    d = Path(args.dir)
    outbox, inbox = d / "outbox.jsonl", d / "inbox.jsonl"
    if not outbox.exists():
        print("[ccdiscuss closed] the discussion is already over")
        return

    # Re-arming after a Monitor timeout: re-send comments that have no reply yet.
    comments, offset = read_jsonl(outbox)
    replies, _ = read_jsonl(inbox)
    last_reply = {}
    for r in replies:
        last_reply[r["thread"]] = max(last_reply.get(r["thread"], 0), r["ts"])
    pending = [c for c in comments if c["type"] == "comment" and c["ts"] > last_reply.get(c["thread"], 0)]
    for c in pending:
        print(format_comment(d, c), flush=True)

    closed = any(c["type"] == "closed" for c in comments)
    while not closed:
        time.sleep(POLL_SECONDS)
        records, offset = read_jsonl(outbox, offset)
        for c in records:
            if c["type"] == "comment":
                print(format_comment(d, c), flush=True)
            elif c["type"] == "closed":
                closed = True
        if not closed and not _window_alive(d):
            closed = True

    print("[ccdiscuss closed] the discussion window was closed", flush=True)
    shutil.rmtree(d, ignore_errors=True)


def cmd_reply(args) -> None:
    d = Path(args.dir)
    if not (d / "inbox.jsonl").exists():
        sys.exit("the discussion window is closed")
    text = sys.stdin.read().strip()
    if not text:
        sys.exit("empty reply")
    append_jsonl(d / "inbox.jsonl", {"type": "reply", "thread": args.thread, "text": text, "ts": time.time()})


def main() -> None:
    parser = argparse.ArgumentParser(prog="ccdiscuss", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("open", help="open a discussion window on the session's last response")
    p.add_argument("session_id")
    p.set_defaults(func=cmd_open)
    p = sub.add_parser("watch", help="print one event per comment until the window closes")
    p.add_argument("dir")
    p.set_defaults(func=cmd_watch)
    p = sub.add_parser("reply", help="post stdin as a reply in a thread")
    p.add_argument("dir")
    p.add_argument("thread")
    p.set_defaults(func=cmd_reply)
    args = parser.parse_args()
    args.func(args)
