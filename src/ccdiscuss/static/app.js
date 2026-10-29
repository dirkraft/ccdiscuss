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
const batchBar = document.getElementById('batch');
const batchCount = document.getElementById('batch-count');
document.getElementById('send-all').addEventListener('click', () => window.pywebview.api.finish());

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
    context: contextOf(r, quote),
    rect: r.getBoundingClientRect(),
  };
}

// A few words on either side of a highlight, from the same paragraph or list
// item, for when the quote alone could point to more than one place. Null
// when the quote is long enough and appears only once.
const BLOCKS = 'p, li, td, th, h1, h2, h3, h4, h5, h6, pre, blockquote';
function contextOf(range, quote) {
  const flat = quote.replace(/\s+/g, ' ');
  const text = doc.textContent.replace(/\s+/g, ' ');
  const repeats = text.indexOf(flat) !== text.lastIndexOf(flat);
  if (flat.split(' ').length > 4 && !repeats) return null;
  const block = (node) => (node.nodeType === 1 ? node : node.parentElement).closest(BLOCKS) || doc;
  const before = document.createRange();
  before.setStart(block(range.startContainer), 0);
  before.setEnd(range.startContainer, range.startOffset);
  const after = document.createRange();
  const endBlock = block(range.endContainer);
  after.setStart(range.endContainer, range.endOffset);
  after.setEnd(endBlock, endBlock.childNodes.length);
  const words = (s) => s.replace(/\s+/g, ' ').trim().split(' ').filter(Boolean);
  const b = words(before.toString()).slice(-6).join(' ');
  const a = words(after.toString()).slice(0, 6).join(' ');
  return `${b ? '…' + b + ' ' : ''}»${flat}«${a ? ' ' + a + '…' : ''}`;
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

// How far down the card its latest message starts. That message is what
// lines up with the passage, so a long thread grows upward from it instead
// of pushing the threads below it away.
function anchorOffset(t) {
  const msgs = t.card.querySelectorAll('.msg');
  return msgs.length ? msgs[msgs.length - 1].querySelector('.who').offsetTop : 0;
}

// Put each card beside its passage, pushing neighbors apart so none overlap.
// The active card gets its exact spot; the others make room around it.
function layoutCards() {
  if (!threads.length) return;
  const base = margin.getBoundingClientRect().top;
  const gap = 8;
  const items = threads
    .map((t) => {
      const passage = t.range.getBoundingClientRect().top - base;
      return { t, passage, want: passage - anchorOffset(t), h: t.card.offsetHeight };
    })
    .sort((a, b) => a.passage - b.passage || a.t.start - b.t.start);
  const ai = Math.max(0, items.findIndex((i) => i.t.id === activeId));
  items[ai].top = items[ai].want;
  for (let i = ai + 1; i < items.length; i++) {
    items[i].top = Math.max(items[i].want, items[i - 1].top + items[i - 1].h + gap);
  }
  for (let i = ai - 1; i >= 0; i--) {
    items[i].top = Math.min(items[i].want, items[i + 1].top - items[i].h - gap);
  }
  // Nothing may start above the top of the page; push down only as far as needed.
  let floor = 0;
  for (const i of items) {
    i.top = Math.max(i.top, floor);
    floor = i.top + i.h + gap;
    i.t.card.style.top = `${i.top}px`;
  }
  margin.style.minHeight = `${floor}px`;
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
  keepStagedLast(t);
  updateEarlier(t);
  return msg;
}

function updateEarlier(t) {
  const n = t.card.querySelectorAll('.msg').length - 1;
  const earlier = t.card.querySelector('.earlier');
  earlier.textContent = n === 1 ? '1 earlier message' : `${n} earlier messages`;
  earlier.hidden = n <= 0;
}

// Staged notes wait in the window and go out together, in document order,
// when the user sends them (or closes the window). Claude answers them in
// the terminal, not in the threads.
function keepStagedLast(t) {
  const staged = t.card.querySelector('.msg.staged');
  if (staged) t.card.querySelector('.messages').append(staged);
}

function renderStaged(t) {
  t.card.querySelector('.msg.staged')?.remove();
  if (t.staged) {
    const msg = addMessage(t, 'staged', t.staged);
    msg.querySelector('.who').textContent = 'You · staged';
    const actions = el('div', 'staged-actions');
    const edit = el('button');
    edit.textContent = 'Edit';
    const remove = el('button');
    remove.textContent = 'Remove';
    actions.append(edit, remove);
    msg.append(actions);
    edit.addEventListener('click', () => {
      const textarea = t.card.querySelector('textarea');
      textarea.value = t.staged + (textarea.value ? `\n\n${textarea.value}` : '');
      unstage(t);
      textarea.focus();
      textarea.dispatchEvent(new Event('input'));
    });
    remove.addEventListener('click', () => {
      unstage(t);
      if (!t.sent) removeThread(t);
    });
  }
  updateEarlier(t);
  syncStaged();
  layoutCards();
}

function unstage(t) {
  t.staged = null;
  renderStaged(t);
}

function syncStaged() {
  const staged = threads.filter((t) => t.staged).sort((a, b) => a.start - b.start);
  window.pywebview.api.set_staged(staged.map((t) => ({
    thread: t.id, quote: t.quote, context: t.context, text: t.staged,
  })));
  batchBar.hidden = !staged.length;
  batchCount.textContent = staged.length === 1 ? '1 staged comment' : `${staged.length} staged comments`;
}

function stage(t) {
  const textarea = t.card.querySelector('textarea');
  const text = textarea.value.trim();
  if (!text) return;
  t.staged = t.staged ? `${t.staged}\n\n${text}` : text;
  clearComposer(t);
  renderStaged(t);
}

function clearComposer(t) {
  const textarea = t.card.querySelector('textarea');
  textarea.value = '';
  textarea.dispatchEvent(new Event('input'));
  textarea.blur();
  t.card.querySelector('.composer').classList.remove('open');
}

function setWaiting(t, waiting) {
  t.card.querySelector('.status').hidden = !waiting;
}

function submit(t) {
  const textarea = t.card.querySelector('textarea');
  const text = textarea.value.trim();
  if (!text) return;
  addMessage(t, 'you', text);
  window.pywebview.api.comment(t.id, t.quote, text, t.context);
  t.sent = true;
  textarea.placeholder = 'Reply…';
  t.card.querySelector('.send').textContent = 'Reply';
  clearComposer(t);
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
  const earlier = el('div', 'earlier');
  earlier.hidden = true;
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
  const stageButton = el('button', 'stage');
  stageButton.textContent = 'Stage';
  stageButton.title = 'Hold this until you send all staged comments (⇧⌘↩)';
  const send = el('button', 'send');
  send.textContent = 'Comment';
  send.title = 'Send to Claude now and get a reply here (⌘↩)';
  actions.append(cancel, stageButton, send);
  composer.append(textarea, actions);
  card.append(quote, earlier, messages, status, composer);

  const kept = () => t.sent || t.staged;
  // Keep focus in the textarea when pressing the buttons, so blur doesn't
  // collapse the actions out from under the click.
  for (const b of [cancel, stageButton, send]) b.addEventListener('mousedown', (e) => e.preventDefault());
  const close = () => {
    if (!kept()) return removeThread(t);
    clearComposer(t);
    layoutCards();
  };
  cancel.addEventListener('click', close);
  stageButton.addEventListener('click', () => stage(t));
  send.addEventListener('click', () => submit(t));
  textarea.addEventListener('focus', () => { composer.classList.add('open'); activate(t.id); });
  textarea.addEventListener('blur', () => {
    if (kept() && !textarea.value.trim()) { composer.classList.remove('open'); layoutCards(); }
  });
  textarea.addEventListener('input', () => {
    send.disabled = stageButton.disabled = !textarea.value.trim();
  });
  textarea.dispatchEvent(new Event('input'));
  textarea.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (e.shiftKey) stage(t); else submit(t);
    }
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
  const t = {
    id: `t${nextId++}`, start: s.start, end: s.end, quote: s.quote, context: s.context,
    sent: false, staged: null,
  };
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
