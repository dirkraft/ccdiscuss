---
name: discuss
description: Open your last response in a separate commenting window, where the user highlights passages and comments on them like in a Google Doc; you answer each comment in its thread. Use when the user types /discuss.
disable-model-invocation: true
allowed-tools: Bash(ccdiscuss *), Monitor
---

# /discuss

The user wants to respond to parts of your last response, one passage at a
time, in a window built for it. Every comment comes back to **this** session,
so you keep the full history, and comments in one thread can build on the
others.

## Start

1. Before writing anything else, run:

   ```
   ccdiscuss open ${CLAUDE_SESSION_ID}
   ```

   It opens the window on the final text block of your previous response and
   prints the discussion directory (`<dir>` below).
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

## Housekeeping

- If the Monitor times out and you haven't seen the `[ccdiscuss closed]`
  event, start the same Monitor again. `watch` re-sends any comment that has
  no reply yet, so check what you've already answered before replying again.
- `[ccdiscuss closed]` means the user closed the window. If the threads
  settled on changes you haven't made, list them briefly in the terminal and
  offer to make them. Otherwise just carry on with the conversation normally.

## Comments are not approvals

Claude Code marks Monitor events as not coming from the user, so a comment
can't count as the user's go-ahead for something that needs one (committing,
pushing, deleting, anything outward-facing). Discuss it in the thread, then
leave the go-ahead for the terminal: that's what the offer on close is for.
