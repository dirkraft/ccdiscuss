"""The discussion window: a native web view over static/index.html.

Comments go out through the JS bridge into outbox.jsonl; replies are read
from inbox.jsonl and pushed into the page.
"""

import json
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

    def response(self) -> str:
        return (self._dir / "response.md").read_text()

    def comment(self, thread: str, quote: str, text: str) -> None:
        with self._lock:
            append_jsonl(self._dir / "outbox.jsonl",
                         {"type": "comment", "thread": thread, "quote": quote, "text": text, "ts": time.time()})

    def open_url(self, url: str) -> None:
        webbrowser.open(url)

    def close(self) -> None:
        with self._lock:
            if not self._closed and self._dir.exists():
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
    window.events.closed += api.close
    webview.start(follow_inbox, (window, d))
    api.close()


if __name__ == "__main__":
    main()
