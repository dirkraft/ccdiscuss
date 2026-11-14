"""ccdiscuss: comment on parts of a Claude Code response in its own window.

A discussion is a temp directory shared by the window and the session:

    response.md    the text being discussed
    source.json    for `open --file`: the file's path, and its language unless
                   it's markdown
    outbox.jsonl   window -> session: comments, then any staged ones as one
                   "batch", then a final "closed"
    inbox.jsonl    session -> window: replies
    window.pid     the window process
    watch.pid      the current `watch`, so the window can tell when nobody's listening

  ccdiscuss open <session-id>      extract the response, launch the window, print the dir
  ccdiscuss open <session-id> --file PATH   discuss a file instead
  ccdiscuss watch <dir>            one stdout event per comment, for the Monitor tool
  ccdiscuss reply <dir> <thread>   post stdin (markdown) as a reply in a thread
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import transcript

POLL_SECONDS = 0.5
MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdx"}
MAX_FILE_BYTES = 2_000_000
WINDOWS = sys.platform == "win32"


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def read_jsonl(path: Path, offset: int = 0) -> tuple[list[dict], int]:
    """Complete records from byte `offset` on, and the offset to resume from."""
    with path.open("rb") as f:
        f.seek(offset)
        data = f.read()
    end = data.rfind(b"\n") + 1  # leave a partially written line for next time
    records = [json.loads(line) for line in data[:end].splitlines() if line.strip()]
    return records, offset + end


def read_source(path: Path) -> tuple[str, dict]:
    """A file to discuss: its text, and how the window should show it."""
    path = path.expanduser().resolve()
    if not path.is_file():
        sys.exit(f"not a file: {path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        sys.exit(f"too big to discuss: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        sys.exit(f"not a text file: {path}")
    # Markdown renders like a response; anything else is code, named for highlight.js.
    lang = None if path.suffix.lower() in MARKDOWN_SUFFIXES else (path.suffix[1:] or path.name).lower()
    return text, {"path": str(path), "lang": lang}


def cmd_open(args) -> None:
    source = None
    if args.file:
        text, source = read_source(Path(args.file))
    else:
        try:
            text = transcript.last_response(transcript.transcript_path(args.session_id))
        except FileNotFoundError as e:
            sys.exit(str(e))
    if not text.strip():
        sys.exit("nothing to discuss: " + ("the file is empty" if source else "no response text found before this prompt"))

    d = Path(tempfile.mkdtemp(prefix="ccdiscuss-"))
    (d / "response.md").write_text(text, encoding="utf-8")
    if source:
        (d / "source.json").write_text(json.dumps(source), encoding="utf-8")
    (d / "outbox.jsonl").touch()
    (d / "inbox.jsonl").touch()
    with (d / "window.log").open("w", encoding="utf-8") as log:
        proc = launch_window(d, log)
    (d / "window.pid").write_text(str(proc.pid))
    print(shell_path(d))


def shell_path(d: Path) -> str:
    """The directory as the session should type it: forward slashes, quoted if
    needed, so it survives Bash on Windows (C:\\Users\\... would lose its backslashes)."""
    return shlex.quote(d.as_posix())


def launch_window(d: Path, log) -> subprocess.Popen:
    """Start the window so it outlives the shell command that opened it."""
    cmd = [sys.executable, "-m", "ccdiscuss.window", str(d)]
    common = dict(stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    if not WINDOWS:
        return subprocess.Popen(cmd, start_new_session=True, **common)
    # No console, its own process group, and out of the caller's job object if
    # allowed, so tools that kill a command's whole job don't take the window with it.
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **common)
    except OSError:  # the job doesn't allow breakaway
        return subprocess.Popen(cmd, creationflags=flags, **common)


def pid_alive(path: Path) -> bool:
    try:
        pid = int(path.read_text())
    except (OSError, ValueError):
        return False
    if WINDOWS:
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _windows_pid_alive(pid: int) -> bool:
    # os.kill(pid, 0) isn't a probe on Windows: signal 0 is CTRL_C_EVENT.
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def quoted(c: dict) -> str:
    """A comment in the terminal's quote-and-reply form."""
    quote = "\n".join("> " + line for line in c["quote"].splitlines())
    if c.get("lines"):  # code: where in the file
        quote += f"\n[lines {c['lines']}]"
    if c.get("context"):  # short or repeated quotes carry their surroundings
        quote += f"\n[context: {c['context']}]"
    return f"{quote}\n{c['text']}"


def source_of(d: Path) -> str:
    """' on <path>' when the discussion is about a file."""
    try:
        return f" on {json.loads((d / 'source.json').read_text(encoding='utf-8'))['path']}"
    except FileNotFoundError:
        return ""


def format_comment(d: Path, c: dict) -> str:
    return (
        f"[ccdiscuss comment{source_of(d)}, thread {c['thread']}]\n"
        f"{quoted(c)}\n"
        f"[reply: ccdiscuss reply {shell_path(d)} {c['thread']} <<'EOF' ... EOF]"
    )


def format_batch(d: Path, b: dict) -> str:
    body = "\n\n".join(quoted(c) for c in b["items"])
    return f"[ccdiscuss staged comments{source_of(d)}: answer in the terminal, not in threads]\n{body}"


def cmd_watch(args) -> None:
    d = Path(args.dir)
    outbox, inbox = d / "outbox.jsonl", d / "inbox.jsonl"
    if not outbox.exists():
        print("[ccdiscuss closed] the discussion is already over")
        return
    (d / "watch.pid").write_text(str(os.getpid()))

    # Re-arming after a Monitor timeout: re-send comments that have no reply yet.
    comments, offset = read_jsonl(outbox)
    replies, _ = read_jsonl(inbox)
    last_reply = {}
    for r in replies:
        last_reply[r["thread"]] = max(last_reply.get(r["thread"], 0), r["ts"])
    pending = [c for c in comments if c["type"] == "comment" and c["ts"] > last_reply.get(c["thread"], 0)]
    for c in pending:
        print(format_comment(d, c), flush=True)
    # A batch is written just before "closed", so one already here hasn't been seen.
    for b in comments:
        if b["type"] == "batch":
            print(format_batch(d, b), flush=True)

    closed = any(c["type"] == "closed" for c in comments)
    while not closed:
        time.sleep(POLL_SECONDS)
        records, offset = read_jsonl(outbox, offset)
        for c in records:
            if c["type"] == "comment":
                print(format_comment(d, c), flush=True)
            elif c["type"] == "batch":
                print(format_batch(d, c), flush=True)
            elif c["type"] == "closed":
                closed = True
        if not closed and not pid_alive(d / "window.pid"):
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
    # Comments go out on stdout and replies come in on stdin, both UTF-8,
    # whatever the console's code page (cp1252 on most Windows machines), and
    # events end in \n everywhere rather than \r\n on Windows.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stdin.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="ccdiscuss", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("open", help="open a discussion window on the session's last response")
    p.add_argument("session_id")
    p.add_argument("--file", help="discuss this file instead of the last response")
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
