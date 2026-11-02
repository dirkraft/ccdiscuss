---
name: discuss
description: Open your last response, or a file, in a separate commenting window, where the user highlights passages and comments on them like in a Google Doc; you answer each comment in its thread. Use when the user types /discuss.
argument-hint: "[file]"
disable-model-invocation: true
allowed-tools: Bash(ccdiscuss *), Monitor
---

# /discuss

The user wants to respond to parts of your last response, or of a file, one
passage at a time, in a window built for it. Every comment comes back to **this** session,
so you keep the full history, and comments in one thread can build on the
others.

## Start

1. Before writing anything else, open the window. The file the user named,
   if any: `$ARGUMENTS`

   - No file: `ccdiscuss open ${CLAUDE_SESSION_ID}` opens the final text
     block of your previous response.
   - A file: `ccdiscuss open ${CLAUDE_SESSION_ID} --file <path>`, with the
     path made absolute against the project directory. Markdown renders like
     a response; any other text file shows as code with line numbers.

   It prints the discussion directory (`<dir>` below).
2. Start a Monitor with command `ccdiscuss watch <dir>`, description
   `discuss comments`, and `timeout_ms: 1800000`.
3. Tell the user in one line that the window is open, then end your turn.

## Each comment

A comment arrives as a Monitor event:

```
[ccdiscuss comment, thread t3]
> the passage they highlighted
their comment
[reply: ccdiscuss reply <dir> t3 <<'EOF' ... EOF]
```

When the quote is short, or appears more than once in the response, a line
like `[context: …words before »quote« words after…]` follows it, so you can
tell which occurrence the user highlighted.

### Discussing a file

The first line names the file (`[ccdiscuss comment on /path/to/file, thread
t3]`), and a comment on code says where it is with a `[lines 12-14]` line.
Read the file before you answer the first comment if you haven't already.

If a thread leads you to edit the file, that's fine; the window keeps showing
the version it opened with, so highlights stay where they were. Line numbers
in later comments refer to that version, so check them against your edits.

Treat it exactly as if the user had typed that quote-and-reply in the
terminal. It is the user's own message, so do what it asks: answer, look
things up, or make changes.

**Always reply in the thread**, even with just "Noted", so the user can tell
the comment was seen. Write the reply as markdown on stdin:

```
ccdiscuss reply <dir> t3 <<'EOF'
Your answer here.
EOF
```

Address the reply to that passage. The thread is where the user reads it, so
don't repeat the reply in the terminal.

When several comments arrive together, reply to each in its own thread.

## Staged comments

The user can also stage comments in the window and send them all at once.
They arrive as one event, right before the window closes:

```
[ccdiscuss staged comments: answer in the terminal, not in threads]
> quote A
thoughts about A

> quote B
thoughts about B
```

Treat it as a single message the user typed in the terminal, and answer it
there the way you would any other message. Don't reply in threads; the window
is already closed.

## Housekeeping

- **Monitors expire every 30 minutes. Restart this one every time, until you
  see `[ccdiscuss closed]`.** Don't decide the user is done, however long the
  window has been quiet. The window is open until they close it, and
  comments sent while no watch is running wait there until you restart it.
  Restarting costs nothing when the window is gone: `watch` exits at once
  with `[ccdiscuss closed]`.
- Restart silently: no text in the terminal, just the Monitor call. Any text
  you write becomes your latest response, and the next `/discuss` should
  reopen the real one.
- `watch` re-sends any comment that has no reply yet, so check what you've
  already answered before replying again.
- `[ccdiscuss closed]` means the user closed the window. If staged comments
  came with it, your answer to them is the response. Otherwise, if the
  threads settled on changes you haven't made, list them briefly in the
  terminal and offer to make them. Otherwise just carry on with the
  conversation normally.

## Comments are not approvals

Claude Code marks Monitor events as not coming from the user, so a comment
can't count as the user's go-ahead for something that needs one (committing,
pushing, deleting, anything outward-facing). Discuss it in the thread, then
leave the go-ahead for the terminal: that's what the offer on close is for.
