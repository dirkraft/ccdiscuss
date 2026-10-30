"""Find a session's transcript and pull out the response to discuss.

Transcripts live at ~/.claude/projects/<dir>/<session-id>.jsonl, one row per
content block (text, thinking, tool_use, tool_result, ...).
"""

import json
import os
from pathlib import Path

PROJECTS_DIR = Path(os.environ.get("CCDISCUSS_PROJECTS_DIR", Path.home() / ".claude" / "projects"))


def transcript_path(session_id: str) -> Path:
    matches = list(PROJECTS_DIR.glob(f"*/{session_id}.jsonl"))
    if not matches:
        raise FileNotFoundError(f"no transcript for session {session_id} under {PROJECTS_DIR}")
    return max(matches, key=lambda p: p.stat().st_mtime)


def _read_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.open():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # the last line can be mid-write
        if row.get("type") in ("user", "assistant") and not row.get("isSidechain"):
            rows.append(row)
    return rows


def _is_prompt(row: dict) -> bool:
    """A turn the user started: typed text or a slash command (/discuss itself)."""
    if row["type"] != "user":
        return False
    if (row.get("origin") or {}).get("kind") == "human":
        return True
    content = row["message"]["content"]
    return isinstance(content, str) and "<command-name>" in content


def _starts_turn(row: dict) -> bool:
    """A prompt or a background notification; tool results continue a turn."""
    if row["type"] != "user" or row.get("isMeta"):
        return False
    content = row["message"]["content"]
    return isinstance(content, str) or any(b.get("type") != "tool_result" for b in content)


def _is_housekeeping(row: dict) -> bool:
    """A turn that only ran a discussion: /discuss itself, a comment answered in
    its thread, a Monitor expiry or the window closing. Staged comments are
    answered in the terminal, so that answer is a real response."""
    text = json.dumps(row["message"]["content"])
    if "<command-name>/discuss</command-name>" in text:
        return True
    return "discuss comments" in text and "[ccdiscuss staged comments" not in text


def last_response(path: Path) -> str:
    """The final text of the response before the newest prompt.

    The newest prompt is the /discuss invocation, so the response to discuss
    comes before it. "Final text" is the run of text blocks after the last
    tool call, which is the part a long answer usually lives in. Turns from an
    earlier discussion are skipped, so /discuss again reopens the same response.
    """
    rows = _read_rows(path)
    prompts = [i for i, r in enumerate(rows) if _is_prompt(r)]
    end = prompts[-1] if prompts else len(rows)

    kept, skipping = [], False
    for row in rows[:end]:
        if _starts_turn(row):
            skipping = _is_housekeeping(row)
        if not skipping:
            kept.append(row)

    texts: list[str] = []
    for row in reversed(kept):
        content = row["message"]["content"]
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        for block in reversed(blocks):
            kind = block.get("type")
            if row["type"] == "assistant" and kind == "text":
                texts.append(block["text"])
            elif kind in ("thinking", "redacted_thinking"):
                continue
            elif texts:
                return "\n\n".join(reversed(texts))
    return "\n\n".join(reversed(texts))
