"""The discussion window: a native web view over static/index.html.

Comments go out through the JS bridge into outbox.jsonl; replies are read
from inbox.jsonl and pushed into the page.
"""

import json
import os
import re
import sys
import threading
import time
import webbrowser
from pathlib import Path

import webview

from .cli import POLL_SECONDS, append_jsonl, read_jsonl

STATIC = Path(__file__).parent / "static"


class Api:
    def __init__(self, d: Path):
        self._dir = d
        self._lock = threading.Lock()
        self._closed = False
        self._staged: list[dict] = []
        self._window = None

    def response(self) -> str:
        return (self._dir / "response.md").read_text()

    def comment(self, thread: str, quote: str, text: str, context: str | None = None) -> None:
        with self._lock:
            append_jsonl(self._dir / "outbox.jsonl",
                         {"type": "comment", "thread": thread, "quote": quote, "context": context,
                          "text": text, "ts": time.time()})

    def set_staged(self, items: list[dict]) -> None:
        """The page's current staged comments, in document order."""
        self._staged = items

    def finish(self) -> None:
        """Send staged comments and close; closing does the sending."""
        self._window.destroy()

    def open_url(self, url: str) -> None:
        webbrowser.open(url)

    def close(self) -> None:
        # Closing the window is "done", so staged comments go out either way.
        with self._lock:
            if not self._closed and self._dir.exists():
                if self._staged:
                    append_jsonl(self._dir / "outbox.jsonl",
                                 {"type": "batch", "items": self._staged, "ts": time.time()})
                append_jsonl(self._dir / "outbox.jsonl", {"type": "closed", "ts": time.time()})
            self._closed = True


def follow_inbox(window, d: Path) -> None:
    offset = 0
    while (d / "inbox.jsonl").exists():
        replies, offset = read_jsonl(d / "inbox.jsonl", offset)
        for r in replies:
            window.evaluate_js(f"ccd.addReply({json.dumps(r['thread'])}, {json.dumps(r['text'])})")
        time.sleep(POLL_SECONDS)


def main() -> None:
    d = Path(sys.argv[1])
    api = Api(d)
    first_line = next((re.sub(r"[#*_`>]", "", l).strip() for l in api.response().splitlines() if l.strip()), "")
    title = "Discuss" + (f": {first_line[:60]}" if first_line else "")
    window = webview.create_window(title, str(STATIC / "index.html"), js_api=api,
                                   width=1240, height=900, text_select=True)
    api._window = window
    window.events.closed += api.close
    webview.start(follow_inbox, (window, d))
    api.close()
    # Don't wait for leftover threads: after "Send staged & close", the bridge
    # call that asked for the close never returns, and waiting on it would
    # leave the dead window on screen.
    os._exit(0)


if __name__ == "__main__":
    main()
