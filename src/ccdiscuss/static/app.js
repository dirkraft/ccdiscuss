// Discussion page: render the response, anchor threads to selected ranges,
// send comments through the pywebview bridge, and show Claude's replies.

const md = window.markdownit({
  linkify: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try { return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value; } catch {}
    }
    return '';
  },
});
const render = (text) => DOMPurify.sanitize(md.render(text));

const doc = document.getElementById('doc');
const margin = document.getElementById('margin');
const addButton = document.getElementById('add-comment');

const threads = [];  // {id, start, end, quote, range, card, sent}
let activeId = null;
let nextId = 1;
let pendingSelection = null;

function el(tag, cls) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  return e;
}

// Threads are anchored by offsets into the doc's text. The rendered response
// never changes after load, so the offsets stay valid.
function offsetOf(node, offset) {
  const r = document.createRange();
  r.setStart(doc, 0);
  r.setEnd(node, offset);
  return r.toString().length;
}

function rangeOf(start, end) {
  const walker = document.createTreeWalker(doc, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  let pos = 0, node, started = false;
  while ((node = walker.nextNode())) {
    const len = node.data.length;
    if (!started && start <= pos + len) { range.setStart(node, start - pos); started = true; }
    if (started && end <= pos + len) { range.setEnd(node, end - pos); break; }
    pos += len;
  }
  return range;
}

function selectionInDoc() {
  const sel = getSelection();
  if (!sel.rangeCount || sel.isCollapsed) return null;
  const r = sel.getRangeAt(0);
  if (!doc.contains(r.startContainer) || !doc.contains(r.endContainer)) return null;
  const quote = sel.toString().trim();
  if (!quote) return null;
  return {
    start: offsetOf(r.startContainer, r.startOffset),
    end: offsetOf(r.endContainer, r.endOffset),
    quote,
    rect: r.getBoundingClientRect(),
  };
}

function updateAddButton() {
  pendingSelection = selectionInDoc();
  if (!pendingSelection) { addButton.hidden = true; return; }
  addButton.style.top = `${pendingSelection.rect.top + scrollY}px`;
  addButton.style.left = `${doc.getBoundingClientRect().right + scrollX + 8}px`;
  addButton.hidden = false;
}

function paintHighlights() {
  if (!window.CSS?.highlights) return;
  CSS.highlights.set('ccd-thread', new Highlight(...threads.map((t) => t.range)));
  const active = threads.find((t) => t.id === activeId);
  if (active) CSS.highlights.set('ccd-active', new Highlight(active.range));
  else CSS.highlights.delete('ccd-active');
}

// Put each card beside its passage, pushing neighbors apart so none overlap.
// The active card gets its exact spot; the others make room around it.
function layoutCards() {
  if (!threads.length) return;
  const base = margin.getBoundingClientRect().top;
  const gap = 8;
  const items = threads
    .map((t) => ({ t, want: t.range.getBoundingClientRect().top - base, h: t.card.offsetHeight }))
    .sort((a, b) => a.want - b.want || a.t.start - b.t.start);
  const ai = Math.max(0, items.findIndex((i) => i.t.id === activeId));
  items[ai].top = items[ai].want;
  for (let i = ai + 1; i < items.length; i++) {
    items[i].top = Math.max(items[i].want, items[i - 1].top + items[i - 1].h + gap);
  }
  for (let i = ai - 1; i >= 0; i--) {
    items[i].top = Math.min(items[i].want, items[i + 1].top - items[i].h - gap);
  }
  const shift = Math.min(0, items[0].top);
  for (const i of items) i.t.card.style.top = `${i.top - shift}px`;
  const last = items[items.length - 1];
  margin.style.minHeight = `${last.top - shift + last.h}px`;
}

function activate(id) {
  activeId = id;
  for (const t of threads) t.card.classList.toggle('active', t.id === id);
  paintHighlights();
  layoutCards();
}

function addMessage(t, who, text) {
  const msg = el('div', `msg ${who}`);
  const label = el('div', 'who');
  label.textContent = who === 'claude' ? 'Claude' : 'You';
  const body = el('div', 'body md');
  body.innerHTML = render(text);
  msg.append(label, body);
  t.card.querySelector('.messages').append(msg);
}

function setWaiting(t, waiting) {
  t.card.querySelector('.status').hidden = !waiting;
}

function submit(t) {
  const textarea = t.card.querySelector('textarea');
  const text = textarea.value.trim();
  if (!text) return;
  addMessage(t, 'you', text);
  window.pywebview.api.comment(t.id, t.quote, text);
  t.sent = true;
  textarea.value = '';
  textarea.placeholder = 'Reply…';
  textarea.blur();
  t.card.querySelector('.send').textContent = 'Reply';
  t.card.querySelector('.composer').classList.remove('open');
  setWaiting(t, true);
  layoutCards();
}

function removeThread(t) {
  threads.splice(threads.indexOf(t), 1);
  t.card.remove();
  if (activeId === t.id) activeId = null;
  paintHighlights();
  layoutCards();
}

function buildCard(t) {
  const card = el('div', 'card');
  const quote = el('div', 'quote');
  quote.textContent = t.quote;
  const messages = el('div', 'messages');
  const status = el('div', 'status');
  status.textContent = 'Waiting for Claude…';
  status.hidden = true;

  const composer = el('div', 'composer open');
  const textarea = el('textarea');
  textarea.placeholder = 'Comment…';
  textarea.rows = 2;
  const actions = el('div', 'actions');
  const cancel = el('button', 'cancel');
  cancel.textContent = 'Cancel';
  const send = el('button', 'send');
  send.textContent = 'Comment';
  send.disabled = true;
  actions.append(cancel, send);
  composer.append(textarea, actions);
  card.append(quote, messages, status, composer);

  // Keep focus in the textarea when pressing the buttons, so blur doesn't
  // collapse the actions out from under the click.
  for (const b of [cancel, send]) b.addEventListener('mousedown', (e) => e.preventDefault());
  const close = () => {
    if (!t.sent) return removeThread(t);
    textarea.value = '';
    send.disabled = true;
    composer.classList.remove('open');
    textarea.blur();
    layoutCards();
  };
  cancel.addEventListener('click', close);
  send.addEventListener('click', () => submit(t));
  textarea.addEventListener('focus', () => { composer.classList.add('open'); activate(t.id); });
  textarea.addEventListener('blur', () => {
    if (t.sent && !textarea.value.trim()) { composer.classList.remove('open'); layoutCards(); }
  });
  textarea.addEventListener('input', () => { send.disabled = !textarea.value.trim(); });
  textarea.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(t); }
    if (e.key === 'Escape') close();
  });
  card.addEventListener('mousedown', () => { if (activeId !== t.id) activate(t.id); });
  new ResizeObserver(() => layoutCards()).observe(card);
  return card;
}

function startThread() {
  const s = pendingSelection || selectionInDoc();
  if (!s) return;
  addButton.hidden = true;
  pendingSelection = null;
  const t = { id: `t${nextId++}`, start: s.start, end: s.end, quote: s.quote, sent: false };
  t.range = rangeOf(t.start, t.end);
  t.card = buildCard(t);
  threads.push(t);
  margin.append(t.card);
  getSelection().removeAllRanges();
  activate(t.id);
  t.card.querySelector('textarea').focus();
}

// Called from Python when Claude replies.
window.ccd = {
  addReply(threadId, text) {
    const t = threads.find((x) => x.id === threadId);
    if (!t) return;
    addMessage(t, 'claude', text);
    setWaiting(t, false);
    layoutCards();
  },
};

document.addEventListener('mouseup', () => setTimeout(updateAddButton, 0));
document.addEventListener('keyup', (e) => { if (e.shiftKey || e.key.startsWith('Arrow')) updateAddButton(); });
addButton.addEventListener('mousedown', (e) => e.preventDefault());
addButton.addEventListener('click', startThread);
document.addEventListener('keydown', (e) => {
  if (e.metaKey && e.altKey && e.code === 'KeyM') { e.preventDefault(); startThread(); }
});

// Clicking highlighted text brings up its thread.
doc.addEventListener('click', (e) => {
  if (!getSelection().isCollapsed) return;
  const caret = document.caretRangeFromPoint(e.clientX, e.clientY);
  if (!caret || !doc.contains(caret.startContainer)) return;
  const off = offsetOf(caret.startContainer, caret.startOffset);
  const hit = threads
    .filter((t) => t.start <= off && off <= t.end)
    .sort((a, b) => (a.end - a.start) - (b.end - b.start))[0];
  if (hit) activate(hit.id);
});

// Links open in the default browser instead of replacing this window.
document.addEventListener('click', (e) => {
  const a = e.target.closest('a[href]');
  if (!a) return;
  e.preventDefault();
  window.pywebview.api.open_url(a.href);
}, true);

window.addEventListener('resize', layoutCards);

async function init() {
  doc.innerHTML = render(await window.pywebview.api.response());
}
if (window.pywebview?.api?.response) init();
else window.addEventListener('pywebviewready', init, { once: true });
