// Second Look — side panel controller.
// WebSocket bridge (see SPEC.md), mic capture (16 kHz PCM16 via AudioWorklet), 24 kHz playback,
// 1 fps tab screenshots, product context tracking and card rendering.
'use strict';

const DEFAULT_URL = 'ws://localhost:8000/ws';
const FRAME_INTERVAL_MS = 1000;
const FRAME_MAX_W = 1024;

const $ = (sel, root = document) => root.querySelector(sel);

/* ------------------------------------------------------------------ *
 * DOM helpers (server data is always inserted as text, never HTML)
 * ------------------------------------------------------------------ */
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : String(v));
    }
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

function icon(id, size = 14) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  const use = document.createElementNS(ns, 'use');
  use.setAttribute('href', '#' + id);
  svg.appendChild(use);
  return svg;
}

const num = (v) => {
  if (v == null || v === '') return null;
  const n = typeof v === 'number' ? v : parseFloat(String(v).replace(/[^0-9.\-]/g, ''));
  return isFinite(n) ? n : null;
};

function money(v, currency, opts = {}) {
  const n = num(v);
  if (n == null) return '—';
  const cur = currency || (S.product && S.product.currency) || 'USD';
  const whole = opts.whole ?? (Math.abs(n) >= 1000 || Number.isInteger(n));
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency', currency: cur,
      minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: whole ? 0 : 2
    }).format(n);
  } catch (_) {
    return '$' + n.toFixed(whole ? 0 : 2);
  }
}

function openUrl(url) {
  if (!url) return;
  try {
    const u = new URL(url);
    if (!/^https?:$/.test(u.protocol)) return;
    chrome.tabs.create({ url: u.href, active: true });
  } catch (_) { /* invalid URL */ }
}

function b64FromBuffer(buf) {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(s);
}

function blobToB64(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',')[1] || '');
    r.onerror = reject;
    r.readAsDataURL(blob);
  });
}

let toastTimer = null;
function toast(msg, kind) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast show' + (kind === 'err' ? ' err' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = 'toast'; }, 3200);
}

/* ------------------------------------------------------------------ *
 * State
 * ------------------------------------------------------------------ */
const S = {
  url: DEFAULT_URL,
  ws: null,
  conn: 'offline',          // offline | connecting | online
  session: 'idle',          // idle | connecting | live
  textSession: false,       // a {start, voice:false} was sent on this socket
  queue: [],
  retryDelay: 1000,
  retryTimer: null,
  liveFallbackTimer: null,

  windowId: null,
  tabId: null,
  product: null,
  productKey: '',
  lastPageSentKey: '',

  mic: null,                // { stream, ctx, node, analyser, sink }
  out: null,                // { ctx, gain, analyser, next, sources }
  frameTimer: null,
  capturing: false,

  savingsCents: null,
  cards: new Map(),         // id -> element
  tools: new Map(),         // id -> element
  bubbles: { user: null, agent: null },
  lastBubbleRole: null,
  lastTyped: { text: '', at: 0 },
  levelRaf: 0
};

/* ------------------------------------------------------------------ *
 * WebSocket
 * ------------------------------------------------------------------ */
function wsOpen() { return S.ws && S.ws.readyState === WebSocket.OPEN; }

function setConn(state, message) {
  S.conn = state;
  renderStatus(message);
}

function connect() {
  if (S.ws && (S.ws.readyState === WebSocket.OPEN || S.ws.readyState === WebSocket.CONNECTING)) return;
  clearTimeout(S.retryTimer);
  setConn('connecting');
  let ws;
  try {
    ws = new WebSocket(S.url);
  } catch (e) {
    setConn('offline', 'Invalid backend URL');
    scheduleRetry();
    return;
  }
  S.ws = ws;
  S.textSession = false;

  ws.onopen = () => {
    if (S.ws !== ws) return;
    S.retryDelay = 1000;
    setConn('online');
    S.lastPageSentKey = '';
    const q = S.queue.splice(0);
    // Make sure the backend knows the product before any start/text message is processed.
    if (S.product && !q.some((m) => m.type === 'page')) sendPage(true);
    for (const m of q) rawSend(m);
  };

  ws.onmessage = (e) => {
    if (S.ws !== ws) return;
    let msg;
    try { msg = JSON.parse(e.data); } catch (_) { return; }
    try { handleServer(msg); } catch (err) { console.error('[second-look] handler', err, msg); }
  };

  ws.onclose = () => {
    if (S.ws !== ws) return;
    S.ws = null;
    S.textSession = false;
    const wasActive = S.session !== 'idle';
    setConn('offline');
    if (wasActive) {
      endSessionLocal();
      toast('Connection lost — retrying…', 'err');
    }
    scheduleRetry();
  };

  ws.onerror = () => { /* onclose follows */ };
}

function scheduleRetry() {
  clearTimeout(S.retryTimer);
  S.retryTimer = setTimeout(connect, S.retryDelay);
  S.retryDelay = Math.min(S.retryDelay * 1.8, 15000);
}

function reconnectNow() {
  S.retryDelay = 1000;
  if (S.ws) {
    const old = S.ws;
    S.ws = null;
    try { old.close(); } catch (_) { /* ignore */ }
  }
  connect();
}

function rawSend(obj) {
  try { S.ws.send(JSON.stringify(obj)); return true; } catch (_) { return false; }
}

// Realtime payloads (audio/frame) are dropped when not connected; control messages queue.
function send(obj) {
  if (wsOpen()) return rawSend(obj);
  if (obj.type !== 'audio' && obj.type !== 'frame') {
    S.queue.push(obj);
    if (S.queue.length > 50) S.queue.shift();
    connect();
  }
  return false;
}

function sendPage(force) {
  if (!S.product) return;
  const key = S.productKey;
  if (!force && key === S.lastPageSentKey) return;
  if (wsOpen()) {
    S.lastPageSentKey = key;
    rawSend({ type: 'page', product: S.product });
  } else if (S.session !== 'idle') {
    send({ type: 'page', product: S.product });
  }
}

/* ------------------------------------------------------------------ *
 * Server message handling
 * ------------------------------------------------------------------ */
function handleServer(msg) {
  switch (msg.type) {
    case 'status': return onStatus(msg);
    case 'audio': return playChunk(msg.data);
    case 'transcript': return onTranscript(msg);
    case 'interrupted': return stopPlayback();
    case 'tool': return onTool(msg);
    case 'card': return msg.card && upsertCard(msg.card);
    case 'savings': return setSavings(msg.total_cents);
    default: return undefined;
  }
}

function onStatus(msg) {
  const st = msg.state;
  if (st === 'connecting') {
    if (S.session !== 'idle') setSession('connecting');
  } else if (st === 'live') {
    clearTimeout(S.liveFallbackTimer);
    if (S.mic) setSession('live');
  } else if (st === 'closed') {
    S.textSession = false;
    if (S.session !== 'idle') endSessionLocal();
  } else if (st === 'error') {
    S.textSession = false;
    toast(msg.message || 'Something went wrong on the server', 'err');
    if (S.session !== 'idle') endSessionLocal();
  }
}

/* ------------------------------------------------------------------ *
 * Session control
 * ------------------------------------------------------------------ */
function setSession(state) {
  S.session = state;
  const mic = $('#micBtn');
  mic.dataset.state = state;
  mic.setAttribute('aria-label', state === 'idle' ? 'Start talking' : 'Stop');
  $('#stage').dataset.state = state;
  updateStageText();
  updateCompact();
  renderStatus();
  if (state === 'idle') stopLevelLoop(); else startLevelLoop();
}

async function startSession() {
  if (S.session !== 'idle') return;
  ensurePlayback();
  setSession('connecting');
  hideMicBanner();

  try {
    await startMic();
  } catch (err) {
    setSession('idle');
    if (err && (err.name === 'NotAllowedError' || err.name === 'SecurityError' || err.name === 'PermissionDeniedError')) {
      showMicBanner('needed');
      openPermissionTab();
    } else if (err && err.name === 'NotFoundError') {
      toast('No microphone found — you can still type below.', 'err');
    } else {
      toast('Could not start the microphone: ' + ((err && err.message) || err), 'err');
    }
    return;
  }

  send({ type: 'start', voice: true });
  S.textSession = true;
  if (S.product) {
    if (wsOpen()) sendPage(true);
    else send({ type: 'page', product: S.product });
  }
  startFrames();

  // If the backend never sends {status:"live"}, flip to live once the socket is up.
  clearTimeout(S.liveFallbackTimer);
  S.liveFallbackTimer = setTimeout(function check() {
    if (S.session !== 'connecting') return;
    if (wsOpen()) setSession('live');
    else S.liveFallbackTimer = setTimeout(check, 1000);
  }, 2500);
}

function stopSession() {
  if (S.session === 'idle') return;
  send({ type: 'stop' });
  S.textSession = false;
  endSessionLocal();
}

function endSessionLocal() {
  clearTimeout(S.liveFallbackTimer);
  stopMic();
  stopFrames();
  stopPlayback();
  finalizeBubbles();
  setSession('idle');
}

/* ------------------------------------------------------------------ *
 * Microphone (AudioWorklet → 16 kHz PCM16 LE, ~100 ms chunks)
 * ------------------------------------------------------------------ */
async function startMic() {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 }
  });
  const ctx = new AudioContext({ latencyHint: 'interactive' });
  try {
    await ctx.audioWorklet.addModule(chrome.runtime.getURL('pcm-worklet.js'));
  } catch (e) {
    stream.getTracks().forEach((t) => t.stop());
    ctx.close();
    throw e;
  }
  const src = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, 'pcm-capture', {
    numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
    processorOptions: { targetRate: 16000, chunkMs: 100 }
  });
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  analyser.smoothingTimeConstant = 0.55;
  const sink = ctx.createGain();
  sink.gain.value = 0; // keep the graph pulled without echoing the mic
  src.connect(analyser);
  src.connect(node);
  node.connect(sink).connect(ctx.destination);

  node.port.onmessage = (e) => {
    if (S.session === 'idle') return;
    send({ type: 'audio', data: b64FromBuffer(e.data) });
  };
  if (ctx.state === 'suspended') await ctx.resume().catch(() => {});

  stream.getAudioTracks().forEach((t) => {
    t.onended = () => { if (S.session !== 'idle') { toast('Microphone disconnected', 'err'); stopSession(); } };
  });

  S.mic = { stream, ctx, node, analyser, sink, buf: new Float32Array(analyser.fftSize) };
  updatePermState('granted');
}

function stopMic() {
  const m = S.mic;
  S.mic = null;
  if (!m) return;
  try { m.node.port.postMessage('flush'); } catch (_) { /* ignore */ }
  try { m.node.port.onmessage = null; m.node.disconnect(); } catch (_) { /* ignore */ }
  m.stream.getTracks().forEach((t) => t.stop());
  m.ctx.close().catch(() => {});
}

function openPermissionTab() {
  chrome.tabs.create({ url: chrome.runtime.getURL('permission.html'), active: true });
}

function showMicBanner(kind) {
  const b = $('#micBanner');
  const t = $('#micBannerText');
  const btn = $('#micBannerBtn');
  b.hidden = false;
  if (kind === 'ready') {
    b.classList.add('ok');
    t.textContent = 'Microphone ready. Tap the mic to start talking.';
    btn.hidden = true;
    setTimeout(hideMicBanner, 5000);
  } else {
    b.classList.remove('ok');
    t.textContent = "Microphone access needed — Chrome can't ask inside a side panel, so we opened a tab for it.";
    btn.hidden = false;
  }
}
function hideMicBanner() { $('#micBanner').hidden = true; }

async function updatePermState(forced) {
  const el = $('#micPermState');
  let st = forced;
  if (!st) {
    try { st = (await navigator.permissions.query({ name: 'microphone' })).state; } catch (_) { st = ''; }
  }
  el.textContent = st === 'granted' ? 'Granted ✓' : st === 'denied' ? 'Blocked' : st ? 'Not granted yet' : '';
}

/* ------------------------------------------------------------------ *
 * Playback (24 kHz PCM16 queue, gapless scheduling)
 * ------------------------------------------------------------------ */
function ensurePlayback() {
  if (!S.out) {
    const ctx = new AudioContext({ sampleRate: 24000, latencyHint: 'interactive' });
    const gain = ctx.createGain();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.6;
    gain.connect(analyser);
    analyser.connect(ctx.destination);
    S.out = { ctx, gain, analyser, next: 0, sources: new Set(), buf: new Float32Array(analyser.fftSize) };
  }
  if (S.out.ctx.state === 'suspended') S.out.ctx.resume().catch(() => {});
  return S.out;
}

function playChunk(b64) {
  if (!b64) return;
  const out = ensurePlayback();
  const bin = atob(b64);
  const len = bin.length >> 1;
  if (!len) return;
  const f32 = new Float32Array(len);
  for (let i = 0, j = 0; i < len; i++, j += 2) {
    let v = bin.charCodeAt(j) | (bin.charCodeAt(j + 1) << 8);
    if (v >= 0x8000) v -= 0x10000;
    f32[i] = v / 0x8000;
  }
  const buffer = out.ctx.createBuffer(1, len, 24000);
  buffer.copyToChannel(f32, 0);
  const src = out.ctx.createBufferSource();
  src.buffer = buffer;
  src.connect(out.gain);
  const now = out.ctx.currentTime;
  if (out.next < now + 0.02) out.next = now + 0.06; // small jitter buffer after an underrun
  src.start(out.next);
  out.next += buffer.duration;
  out.sources.add(src);
  src.onended = () => out.sources.delete(src);
  if (S.session === 'idle') startLevelLoop();
}

function stopPlayback() {
  const out = S.out;
  if (!out) return;
  for (const s of out.sources) {
    try { s.onended = null; s.stop(); s.disconnect(); } catch (_) { /* already stopped */ }
  }
  out.sources.clear();
  out.next = 0;
}

/* ------------------------------------------------------------------ *
 * Audio level → mic ring animation
 * ------------------------------------------------------------------ */
function rms(analyser, buf) {
  analyser.getFloatTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
  return Math.sqrt(sum / buf.length);
}

let smoothLevel = 0;
function levelTick() {
  const mic = $('#micBtn');
  const inL = S.mic ? Math.min(1, rms(S.mic.analyser, S.mic.buf) * 5) : 0;
  const outPlaying = S.out && S.out.sources.size > 0;
  const outL = outPlaying ? Math.min(1, rms(S.out.analyser, S.out.buf) * 4) : 0;
  const target = Math.max(inL, outL);
  smoothLevel += (target - smoothLevel) * (target > smoothLevel ? 0.5 : 0.15);
  mic.style.setProperty('--level', smoothLevel.toFixed(3));
  mic.dataset.speaker = outL > inL * 1.2 && outL > 0.03 ? 'agent' : 'user';
  if (S.session === 'idle' && !outPlaying && smoothLevel < 0.01) {
    stopLevelLoop();
    return;
  }
  S.levelRaf = requestAnimationFrame(levelTick);
}
function startLevelLoop() { if (!S.levelRaf) S.levelRaf = requestAnimationFrame(levelTick); }
function stopLevelLoop() {
  cancelAnimationFrame(S.levelRaf);
  S.levelRaf = 0;
  smoothLevel = 0;
  $('#micBtn').style.setProperty('--level', '0');
}

/* ------------------------------------------------------------------ *
 * Screen frames (1 fps captureVisibleTab → ≤1024 px JPEG)
 * ------------------------------------------------------------------ */
function startFrames() {
  stopFrames();
  captureFrame();
  S.frameTimer = setInterval(captureFrame, FRAME_INTERVAL_MS);
}
function stopFrames() {
  clearInterval(S.frameTimer);
  S.frameTimer = null;
}

async function captureFrame() {
  if (S.capturing || !wsOpen() || S.session === 'idle') return;
  S.capturing = true;
  try {
    if (S.windowId == null) S.windowId = (await chrome.windows.getCurrent()).id;
    const dataUrl = await chrome.tabs.captureVisibleTab(S.windowId, { format: 'jpeg', quality: 50 });
    if (!dataUrl) return;
    const blob = await (await fetch(dataUrl)).blob();
    const bmp = await createImageBitmap(blob);
    let b64;
    if (bmp.width > FRAME_MAX_W) {
      const scale = FRAME_MAX_W / bmp.width;
      const w = FRAME_MAX_W;
      const hgt = Math.round(bmp.height * scale);
      const canvas = new OffscreenCanvas(w, hgt);
      const g = canvas.getContext('2d');
      g.imageSmoothingQuality = 'high';
      g.drawImage(bmp, 0, 0, w, hgt);
      b64 = await blobToB64(await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.6 }));
    } else {
      b64 = dataUrl.slice(dataUrl.indexOf(',') + 1);
    }
    bmp.close();
    if (b64 && S.session !== 'idle') send({ type: 'frame', data: b64 });
  } catch (_) {
    // chrome:// pages, devtools, PDF viewers, rate limits — just skip this frame.
  } finally {
    S.capturing = false;
  }
}

/* ------------------------------------------------------------------ *
 * Product context (content script ⇄ panel)
 * ------------------------------------------------------------------ */
const isWebUrl = (u) => /^https?:\/\//i.test(u || '');

async function askTab(tabId) {
  const ask = () => chrome.tabs.sendMessage(tabId, { type: 'sl:getProduct' });
  try {
    const r = await ask();
    return r ? r.product || null : null;
  } catch (_) {
    try {
      await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] });
      const r = await ask();
      return r ? r.product || null : null;
    } catch (_e) {
      return undefined; // can't script this page (chrome web store, etc.)
    }
  }
}

let refreshSeq = 0;
async function refreshActiveTab() {
  const seq = ++refreshSeq;
  let tab;
  try {
    if (S.windowId == null) S.windowId = (await chrome.windows.getCurrent()).id;
    [tab] = await chrome.tabs.query({ active: true, windowId: S.windowId });
  } catch (_) { return; }
  if (!tab || seq !== refreshSeq) return;
  const switched = S.tabId !== tab.id;
  S.tabId = tab.id;

  if (!isWebUrl(tab.url)) { setProduct(null); return; }

  if (switched) {
    // Instant render from the background cache while we ask the page.
    try {
      const k = 'product:' + tab.id;
      const cached = (await chrome.storage.session.get(k))[k];
      if (cached && seq === refreshSeq) setProduct(cached);
    } catch (_) { /* ignore */ }
  }
  const p = await askTab(tab.id);
  if (seq !== refreshSeq) return;
  if (p !== undefined) setProduct(p);
  else if (switched) setProduct(null);
}

function productKeyOf(p) {
  return p ? JSON.stringify(p) : '';
}

function setProduct(p) {
  const key = productKeyOf(p);
  if (key === S.productKey) return;
  const prevId = S.product && (S.product.asin || S.product.url);
  S.product = p || null;
  S.productKey = key;
  renderProduct(prevId !== (p && (p.asin || p.url)));
  if (p) sendPage(false);
}

let tabRefreshTimer = null;
function scheduleRefresh(ms = 250) {
  clearTimeout(tabRefreshTimer);
  tabRefreshTimer = setTimeout(refreshActiveTab, ms);
}

/* ------------------------------------------------------------------ *
 * Rendering — header / product / stage
 * ------------------------------------------------------------------ */
function renderStatus(message) {
  const pill = $('#statusPill');
  let state = S.conn;
  let label = { offline: 'Offline', connecting: 'Connecting', online: 'Ready' }[S.conn];
  if (S.conn === 'online' && S.session === 'live') { state = 'live'; label = 'Live'; }
  if (S.conn === 'offline') label = 'Offline · Retry';
  pill.dataset.state = state;
  $('.label', pill).textContent = label;
  pill.title = message || (S.conn === 'offline' ? `Can't reach ${S.url} — click to retry` : S.url);
  updateStageText();
}

function renderProduct(changedProduct) {
  const p = S.product;
  const card = $('#product');
  card.classList.toggle('empty', !p);
  if (changedProduct) {
    card.classList.remove('flash');
    void card.offsetWidth;
    card.classList.add('flash');
  }
  const img = $('#productImg');
  if (p && p.image) {
    if (img.getAttribute('src') !== p.image) img.src = p.image;
  } else {
    img.removeAttribute('src');
  }
  $('#productSite').textContent = p ? (p.brand ? `${p.brand} · ${p.site || ''}` : p.site || 'Product') : 'No product detected';
  $('#productTitle').textContent = p ? p.title : 'Open a product page on Amazon, Best Buy, Walmart or Target.';
  $('#productPrice').textContent = p && p.price != null ? money(p.price, p.currency, { whole: false }) : '';
  $('#productList').textContent = p && p.list_price != null && p.list_price > (p.price || 0) ? money(p.list_price, p.currency, { whole: false }) : '';
  const r = $('#productRating');
  r.textContent = '';
  if (p && p.rating != null) {
    r.append(icon('i-star', 12), `${Number(p.rating).toFixed(1)}`);
    if (p.review_count) r.append(h('span', { class: 'muted' }, ` (${Number(p.review_count).toLocaleString()})`));
  }
  updateStageText();
}

function updateCompact() {
  const compact = S.session !== 'idle' || S.cards.size > 0 || $('#transcript').childElementCount > 0;
  $('#stage').classList.toggle('compact', compact);
}

let captionText = '';
function updateStageText() {
  const title = $('#stageTitle');
  const sub = $('#stageSub');
  sub.classList.remove('caption');
  if (S.session === 'connecting') {
    title.textContent = 'Connecting…';
    sub.textContent = 'Warming up your shopping copilot.';
  } else if (S.session === 'live') {
    title.textContent = 'Listening';
    if (captionText) { sub.textContent = captionText; sub.classList.add('caption'); }
    else sub.textContent = S.product ? 'Ask: “Is this actually a good deal?”' : 'Open a product and ask away.';
  } else if (S.conn === 'offline') {
    title.textContent = 'Backend offline';
    sub.textContent = 'Start the server, then tap the status pill to retry.';
  } else {
    title.textContent = S.cards.size ? 'Ask a follow-up' : 'Take a second look';
    sub.textContent = S.product
      ? 'Tap the mic and ask if this is worth buying.'
      : 'Open a product page, then tap the mic.';
  }
}

/* ------------------------------------------------------------------ *
 * Transcript
 * ------------------------------------------------------------------ */
function finalizeBubbles() {
  for (const role of ['user', 'agent']) {
    const b = S.bubbles[role];
    if (b) b.classList.remove('partial');
    S.bubbles[role] = null;
  }
}

function onTranscript(msg) {
  const role = msg.role === 'user' ? 'user' : 'agent';
  const text = msg.text || '';

  // Skip server echoes of what the user just typed (already shown locally).
  if (role === 'user' && S.lastTyped.text && Date.now() - S.lastTyped.at < 4000) {
    const t = text.trim();
    if (!t || S.lastTyped.text.startsWith(t) || t === S.lastTyped.text) {
      if (msg.final) S.lastTyped.text = '';
      return;
    }
  }
  if (!text && !msg.final) return;

  // A new speaker closes the other role's in-progress bubble so ordering stays correct.
  const other = role === 'user' ? 'agent' : 'user';
  if (S.bubbles[other] && S.lastBubbleRole === other) {
    S.bubbles[other].classList.remove('partial');
    S.bubbles[other] = null;
  }

  let b = S.bubbles[role];
  if (!b) {
    if (!text) return;
    b = h('div', { class: `bubble ${role} partial` });
    b._text = '';
    $('#transcript').append(b);
    S.bubbles[role] = b;
    $('#convoSection').hidden = false;
    updateCompact();
  }
  S.lastBubbleRole = role;

  if (msg.final) {
    // Final may carry the full utterance or just the last delta.
    const acc = b._text;
    if (text) {
      if (!acc || text.startsWith(acc.trim()) || text.length >= acc.length * 0.9 && text.includes(acc.trim().slice(0, 20))) b._text = text;
      else if (!acc.endsWith(text)) b._text = acc + text;
    }
    b.textContent = b._text.trim();
    b.classList.remove('partial');
    S.bubbles[role] = null;
  } else {
    b._text += text;
    b.textContent = b._text.trimStart();
  }

  if (role === 'agent') {
    captionText = b._text.trim().split(/(?<=[.!?])\s+/).slice(-2).join(' ');
    updateStageText();
  }
  scrollToBottomIfNear();
}

function addLocalUserBubble(text) {
  finalizeBubbles();
  const b = h('div', { class: 'bubble user' }, text);
  $('#transcript').append(b);
  $('#convoSection').hidden = false;
  S.lastBubbleRole = 'user';
  updateCompact();
  scrollToBottom();
}

function scrollToBottomIfNear() {
  const sc = $('#scroll');
  if (sc.scrollHeight - sc.scrollTop - sc.clientHeight < 160) sc.scrollTop = sc.scrollHeight;
}
function scrollToBottom() {
  const sc = $('#scroll');
  sc.scrollTop = sc.scrollHeight;
}

/* ------------------------------------------------------------------ *
 * Tool activity chips
 * ------------------------------------------------------------------ */
function onTool(msg) {
  const id = msg.id || msg.name || String(Date.now());
  const wrap = $('#activity');
  wrap.hidden = false;
  let chip = S.tools.get(id);
  if (!chip) {
    chip = h('div', { class: 'chip' }, h('span', { class: 'ind' }), h('span', { class: 'chip-label' }));
    wrap.append(chip);
    S.tools.set(id, chip);
    // Keep the row tidy: fade older finished chips and cap the count.
    const chips = [...wrap.children];
    chips.slice(0, -4).forEach((c) => { if (c.dataset.state !== 'running') c.classList.add('old'); });
    while (wrap.children.length > 8) {
      const first = wrap.firstElementChild;
      for (const [k, v] of S.tools) if (v === first) S.tools.delete(k);
      first.remove();
    }
  }
  const state = msg.state || 'running';
  chip.dataset.state = state;
  const label = $('.chip-label', chip);
  label.textContent = msg.label || prettyToolName(msg.name);
  label.classList.toggle('shimmer', state === 'running');
  const ind = $('.ind', chip);
  ind.textContent = '';
  if (state === 'done') ind.append(icon('i-check', 12));
  if (state === 'error') ind.append(icon('i-x', 11));
}

function prettyToolName(n) {
  if (!n) return 'Working';
  const s = String(n).replace(/[_-]+/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/* ------------------------------------------------------------------ *
 * Cards
 * ------------------------------------------------------------------ */
const KIND_ORDER = { verdict: 0, price: 1, reviews: 2, stores: 3, alternatives: 4, cost: 5, watch: 6, email: 7 };

function upsertCard(card) {
  const id = card.id || card.kind || String(Date.now());
  let el;
  try {
    el = renderCard(card);
  } catch (e) {
    console.error('[second-look] card render failed', e, card);
    el = cardShell(card, 'i-spark', prettyToolName(card.kind), h('div', { class: 'kv' }, h('pre', null, JSON.stringify(card, null, 2))));
  }
  el.dataset.id = id;
  el.style.order = String(KIND_ORDER[card.kind] ?? 9);
  const existing = S.cards.get(id);
  if (existing && existing.isConnected) {
    el.style.animation = 'none';
    existing.replaceWith(el);
    requestAnimationFrame(() => { el.style.animation = ''; el.classList.add('updated'); });
  } else {
    $('#cards').append(el);
  }
  S.cards.set(id, el);
  $('#insightsSection').hidden = false;
  updateCompact();
  updateStageText();
  // Animate bars after insertion so CSS transitions run.
  requestAnimationFrame(() => requestAnimationFrame(() => {
    el.querySelectorAll('[data-w]').forEach((n) => { n.style.width = n.dataset.w; });
    el.querySelectorAll('[data-grow]').forEach((n) => { n.style.flexGrow = n.dataset.grow; });
    el.querySelectorAll('.mail-body').forEach((n) => { if (n.scrollHeight <= n.clientHeight + 2) n.classList.add('fits'); });
  }));
  if (!existing) {
    setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: card.kind === 'verdict' ? 'start' : 'nearest' }), 60);
  }
}

function cardShell(card, iconId, title, ...body) {
  const meta = body.length && body[0] && body[0].__meta ? body.shift().node : null;
  return h('article', { class: `card ${card.kind || ''}` },
    h('div', { class: 'card-head' },
      h('span', { class: 'card-icon' }, icon(iconId, 14)),
      h('span', { class: 'card-title' }, title),
      meta),
    ...body);
}
const metaNode = (node) => ({ __meta: true, node });

function renderCard(c) {
  switch (c.kind) {
    case 'verdict': return renderVerdict(c);
    case 'reviews': return renderReviews(c);
    case 'price': return renderPrice(c);
    case 'stores': return renderStores(c);
    case 'alternatives': return renderAlternatives(c);
    case 'cost': return renderCost(c);
    case 'watch': return renderWatch(c);
    case 'email': return renderEmail(c);
    default:
      return cardShell(c, 'i-spark', prettyToolName(c.kind || 'Note'),
        h('div', { class: 'kv' }, h('pre', null, JSON.stringify(c, null, 2))));
  }
}

const pct = (v) => {
  const n = num(v);
  if (n == null) return null;
  return Math.max(0, Math.min(100, n <= 1 ? n * 100 : n));
};

const VERDICT = {
  BUY_NOW: { label: 'Buy now', icon: 'i-check', color: 'var(--green)' },
  WAIT: { label: 'Wait', icon: 'i-chart', color: 'var(--amber)' },
  SKIP: { label: 'Skip', icon: 'i-x', color: 'var(--red)' },
  BUY_ALTERNATIVE: { label: 'Buy alternative', icon: 'i-swap', color: 'var(--blue)' }
};

function renderVerdict(c) {
  const key = String(c.verdict || '').toUpperCase();
  const v = VERDICT[key] || { label: key || 'Verdict', icon: 'i-spark', color: 'var(--accent)' };
  const conf = pct(c.confidence);
  const el = h('article', { class: 'card verdict', dataset: { v: key } },
    h('div', { class: 'verdict-top' },
      h('span', { class: 'verdict-badge' }, icon(v.icon, 14), v.label),
      h('span', { class: 'verdict-eyebrow' }, 'Second Look verdict')),
    c.headline ? h('div', { class: 'verdict-headline' }, c.headline) : null,
    conf != null ? h('div', { class: 'conf' },
      h('div', { class: 'conf-row' }, h('span', null, 'Confidence'), h('b', { class: 'num' }, `${Math.round(conf)}%`)),
      h('div', { class: 'bar' }, h('i', { 'data-w': conf + '%' }))) : null,
    Array.isArray(c.reasons) && c.reasons.length
      ? h('ol', { class: 'reasons' }, c.reasons.map((r, i) => h('li', { style: { animationDelay: `${0.15 + i * 0.08}s` } }, r)))
      : null);

  const probs = c.probabilities && typeof c.probabilities === 'object' ? Object.entries(c.probabilities) : [];
  const vals = probs.map(([k, p]) => [k, pct(p)]).filter(([, p]) => p != null && p > 0);
  if (vals.length > 1) {
    const colorOf = (k) => (VERDICT[String(k).toUpperCase()] || {}).color || 'var(--text-3)';
    el.append(h('div', { class: 'probs' },
      h('div', { class: 'probs-bar' }, vals.map(([k, p]) => h('i', { 'data-grow': String(p), style: { flexGrow: '0', flexBasis: '0', background: colorOf(k) } }))),
      h('div', { class: 'probs-legend' }, vals.map(([k, p]) =>
        h('span', { style: { '--c': colorOf(k) } }, `${(VERDICT[String(k).toUpperCase()] || {}).label || k} ${Math.round(p)}%`)))));
  }
  return el;
}

function stars(rating) {
  const r = num(rating);
  const w = r == null ? 0 : Math.max(0, Math.min(5, r)) / 5 * 100;
  return h('span', { class: 'stars', 'aria-label': r == null ? '' : `${r} out of 5` }, h('i', { 'data-w': w + '%' }));
}

function renderReviews(c) {
  const shown = num(c.shown_rating);
  const real = num(c.real_rating);
  const delta = shown != null && real != null ? real - shown : null;
  const ratings = h('div', { class: 'ratings' },
    h('div', { class: 'rating-col shown' },
      h('span', { class: 'rating-lbl' }, 'Shown'),
      h('span', { class: 'rating-num num' }, shown != null ? shown.toFixed(1) : '—'),
      stars(shown)),
    delta != null
      ? h('span', { class: 'delta num' + (delta >= -0.05 ? ' good' : '') }, `${delta >= 0 ? '+' : '−'}${Math.abs(delta).toFixed(1)}★`)
      : h('span'),
    h('div', { class: 'rating-col real' },
      h('span', { class: 'rating-lbl' }, 'Real'),
      h('span', { class: 'rating-num num' }, real != null ? real.toFixed(1) : '—'),
      stars(real)));

  const list = (arr) => (Array.isArray(arr) ? arr.slice(0, 5).map((t) => h('li', null, t)) : []);
  const pros = list(c.pros);
  const cons = list(c.cons);
  const pc = pros.length || cons.length
    ? h('div', { class: 'proscons' },
      pros.length ? h('div', { class: 'pc-col pros' }, h('h4', null, 'Pros'), h('ul', null, pros)) : null,
      cons.length ? h('div', { class: 'pc-col cons' }, h('h4', null, 'Cons'), h('ul', null, cons)) : null)
    : null;

  const inc = pct(c.incentivized_pct);
  const incent = inc != null
    ? h('div', { class: 'incent' },
      h('div', { class: 'conf-row' }, h('span', null, 'Incentivized / suspicious reviews'), h('b', { class: 'num' }, `${Math.round(inc)}%`)),
      h('div', { class: 'bar' }, h('i', { 'data-w': inc + '%' })))
    : null;

  const sources = Array.isArray(c.sources) && c.sources.length
    ? h('div', { class: 'sources' }, c.sources.slice(0, 6).map((s) => {
      const title = (s && (s.title || s.url)) || 'Source';
      let host = '';
      try { host = new URL(s.url).hostname.replace(/^www\./, ''); } catch (_) { /* ignore */ }
      return h('a', { class: 'src', title: s.url || '', onclick: (e) => { e.preventDefault(); openUrl(s.url); }, href: '#' },
        icon('i-ext', 10), h('span', null, title.length > 40 && host ? host : title));
    }))
    : null;

  return cardShell(c, 'i-star', 'Review check',
    metaNode(c.sources && c.sources.length ? h('span', { class: 'card-meta' }, `${c.sources.length} sources`) : null),
    ratings, pc, incent, sources);
}

function toTime(t, i) {
  if (typeof t === 'number') return t < 1e11 ? t * 1000 : t;
  const n = Date.parse(t);
  return isFinite(n) ? n : i;
}

let chartSeq = 0;
function priceChart(c) {
  const pts = (Array.isArray(c.history) ? c.history : [])
    .map((p, i) => ({ t: toTime(p && (p.t ?? p.date ?? p.time), i), v: num(p && (p.price ?? p.v)) }))
    .filter((p) => p.v != null)
    .sort((a, b) => a.t - b.t);
  const cur = num(c.current);
  if (cur != null && pts.length && Math.abs(pts[pts.length - 1].v - cur) > 0.005) {
    pts.push({ t: Math.max(Date.now(), pts[pts.length - 1].t + 1), v: cur });
  }
  if (pts.length < 2) return null;

  const W = 320, H = 118, PT = 12, PB = 18, PL = 2, PR = 2;
  const low = num(c.low), avg = num(c.avg), high = num(c.high);
  const vals = pts.map((p) => p.v).concat([low, avg, high].filter((x) => x != null));
  let min = Math.min(...vals), max = Math.max(...vals);
  if (max - min < 0.01) { max += 1; min -= 1; }
  const padV = (max - min) * 0.12;
  min -= padV; max += padV;
  const t0 = pts[0].t, t1 = pts[pts.length - 1].t;
  const x = (t) => PL + ((t - t0) / Math.max(1, t1 - t0)) * (W - PL - PR);
  const y = (v) => PT + (1 - (v - min) / (max - min)) * (H - PT - PB);

  // Step line (prices change discretely)
  let d = `M${x(pts[0].t).toFixed(1)},${y(pts[0].v).toFixed(1)}`;
  let len = 0;
  for (let i = 1; i < pts.length; i++) {
    const px = x(pts[i].t), py = y(pts[i].v), prevY = y(pts[i - 1].v), prevX = x(pts[i - 1].t);
    d += ` H${px.toFixed(1)} V${py.toFixed(1)}`;
    len += Math.abs(px - prevX) + Math.abs(py - prevY);
  }
  const lastX = x(pts[pts.length - 1].t), lastY = y(pts[pts.length - 1].v);
  const baseY = H - PB;
  const area = `${d} V${baseY} H${x(pts[0].t).toFixed(1)} Z`;
  const gid = 'pg' + (++chartSeq);

  const fmtDate = (t) => {
    if (t < 1e9) return '';
    return new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  };
  const ref = (v, cls, label, anchorRight) => {
    if (v == null) return '';
    const yy = y(v).toFixed(1);
    const tx = anchorRight ? W - PR : PL + 2;
    const anchor = anchorRight ? 'end' : 'start';
    return `<line class="ref ${cls}" x1="${PL}" x2="${W - PR}" y1="${yy}" y2="${yy}"/>` +
      `<text class="lbl ${cls}" x="${tx}" y="${(+yy - 4).toFixed(1)}" text-anchor="${anchor}">${esc(label)}</text>`;
  };

  const svg = `
<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Price history">
  <defs>
    <linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" style="stop-color:var(--accent);stop-opacity:.35"/>
      <stop offset="1" style="stop-color:var(--accent);stop-opacity:0"/>
    </linearGradient>
  </defs>
  <path class="area" d="${area}" fill="url(#${gid})"/>
  ${ref(avg, 'avg', `avg ${money(avg)}`, true)}
  ${ref(low, 'low', `low ${money(low)}`, false)}
  <path class="line" d="${d}" style="--len:${Math.ceil(len + 10)}"/>
  <circle class="now-ring" cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="4"/>
  <circle class="now" cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="3.5"/>
  <text class="axis" x="${PL}" y="${H - 3}" text-anchor="start">${esc(fmtDate(t0))}</text>
  <text class="axis" x="${W - PR}" y="${H - 3}" text-anchor="end">${esc(fmtDate(t1) && 'Today')}</text>
</svg>`;
  const wrap = h('div');
  wrap.innerHTML = svg; // only numbers + escaped labels are interpolated
  return wrap.firstElementChild;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function renderPrice(c) {
  const listP = num(c.list_price);
  const cur = num(c.current);
  const top = h('div', { class: 'price-row' },
    h('div', { class: 'price-now num' }, money(cur, null, { whole: false }),
      listP != null && cur != null && listP > cur ? h('small', null, money(listP, null, { whole: false })) : null),
    c.fake_discount ? h('span', { class: 'fake-pill' }, icon('i-warn', 11), 'FAKE DISCOUNT') : null,
    c.demo_data ? h('span', { class: 'demo-pill', title: 'Price history includes seeded demo rows' }, 'demo data') : null);

  const chart = priceChart(c);
  const stats = h('div', { class: 'stats' },
    h('div', { class: 'stat low' }, h('div', { class: 'stat-l' }, 'Low'), h('div', { class: 'stat-v num' }, money(c.low, null, { whole: false }))),
    h('div', { class: 'stat' }, h('div', { class: 'stat-l' }, 'Avg'), h('div', { class: 'stat-v num' }, money(c.avg, null, { whole: false }))),
    h('div', { class: 'stat' }, h('div', { class: 'stat-l' }, 'High'), h('div', { class: 'stat-v num' }, money(c.high, null, { whole: false }))));

  let meta = null;
  if (cur != null && num(c.avg) != null) {
    const diff = (cur - num(c.avg)) / num(c.avg) * 100;
    meta = h('span', { class: 'card-meta num', style: { color: diff <= -1 ? 'var(--green)' : diff >= 1 ? 'var(--red)' : '' } },
      `${diff > 0 ? '+' : ''}${diff.toFixed(0)}% vs avg`);
  }
  return cardShell(c, 'i-chart', 'Price history', metaNode(meta), top, chart, stats,
    c.note ? h('div', { class: 'note' }, c.note) : null);
}

function renderStores(c) {
  const offers = Array.isArray(c.offers) ? c.offers.slice() : [];
  const priceOf = (o) => num(o.total) ?? num(o.price);
  const bestStore = c.best && c.best.store
    ? String(c.best.store).toLowerCase()
    : (offers.filter((o) => priceOf(o) != null).sort((a, b) => priceOf(a) - priceOf(b))[0] || {}).store?.toLowerCase();
  offers.sort((a, b) => (priceOf(a) ?? Infinity) - (priceOf(b) ?? Infinity));

  const rows = offers.map((o, i) => {
    const isBest = bestStore && String(o.store || '').toLowerCase() === bestStore;
    const stock = o.in_stock === false ? 'out' : o.in_stock === true ? '' : 'unk';
    const hasTotal = num(o.total) != null && num(o.price) != null && Math.abs(num(o.total) - num(o.price)) > 0.005;
    return h('a', {
      class: 'offer' + (isBest ? ' best' : ''), href: '#', title: o.url || '',
      style: { animationDelay: `${i * 0.06}s` },
      onclick: (e) => { e.preventDefault(); openUrl(o.url); }
    },
    h('div', null,
      h('div', { class: 'offer-store' },
        h('span', { class: 'stock ' + stock, title: o.in_stock === false ? 'Out of stock' : o.in_stock ? 'In stock' : 'Stock unknown' }),
        h('span', { class: 'nm' }, o.store || 'Store'),
        isBest ? h('span', { class: 'best-tag' }, 'Best') : null),
      o.note ? h('div', { class: 'offer-note' }, o.note) : null),
    h('div', { class: 'offer-price num' }, money(priceOf(o), null, { whole: false }),
      hasTotal ? h('small', null, `${money(o.price, null, { whole: false })} + ship/tax`) : null),
    h('span', { class: 'offer-go' }, icon('i-ext', 13)));
  });

  const saving = c.best && num(c.best.saving);
  return cardShell(c, 'i-store', 'Other stores',
    metaNode(h('span', { class: 'card-meta' }, `${offers.length} offer${offers.length === 1 ? '' : 's'}`)),
    h('div', { class: 'offers' }, rows),
    saving != null && saving > 0
      ? h('div', { class: 'save-banner' }, icon('i-coins', 15), `Save ${money(saving, null, { whole: false })} at ${c.best.store}`)
      : null);
}

function renderAlternatives(c) {
  const items = Array.isArray(c.items) ? c.items : [];
  return cardShell(c, 'i-swap', 'Better alternatives',
    h('div', null, items.map((it, i) => h('div', {
      class: 'alt', style: { animationDelay: `${i * 0.07}s` }, title: it.url || '',
      onclick: () => openUrl(it.url)
    },
    h('div', { class: 'alt-title' }, it.title || 'Alternative'),
    h('div', { class: 'alt-price num' }, it.price != null ? (num(it.price) != null ? money(it.price, null, { whole: false }) : String(it.price)) : ''),
    it.why ? h('div', { class: 'alt-why' }, it.why) : null))));
}

function renderCost(c) {
  const y = num(c.yearly_extra);
  return cardShell(c, 'i-coins', 'True cost of ownership',
    h('div', { class: 'big-num num' }, y != null ? `+${money(y, null, { whole: false })}` : '—', h('small', null, '/ year')),
    Array.isArray(c.items) && c.items.length ? h('ul', { class: 'bullets' }, c.items.map((t) => h('li', null, t))) : null);
}

function renderWatch(c) {
  const target = num(c.target_price), cur = num(c.current);
  const gap = target != null && cur != null ? cur - target : null;
  return cardShell(c, 'i-bell', 'Price watch',
    metaNode(h('span', { class: 'card-meta', style: { display: 'inline-flex', alignItems: 'center', gap: '6px' } }, h('span', { class: 'live-dot' }), 'Active')),
    c.title ? h('div', { class: 'watch-title' }, c.title) : null,
    h('div', { class: 'watch-prices' },
      h('div', { class: 'watch-p' }, h('div', { class: 'stat-l' }, 'Now'), h('div', { class: 'stat-v num' }, money(cur, null, { whole: false }))),
      h('div', { class: 'watch-arrow' }),
      h('div', { class: 'watch-p target' }, h('div', { class: 'stat-l' }, 'Target'), h('div', { class: 'stat-v num' }, money(target, null, { whole: false })))),
    h('div', { class: 'watch-foot' },
      gap != null && gap > 0
        ? `We'll email you when it drops ${money(gap, null, { whole: false })} more.`
        : "We'll email you the moment it hits your target."));
}

function renderEmail(c) {
  const status = String(c.status || 'draft').toLowerCase();
  const body = h('div', { class: 'mail-body', title: 'Click to expand' }, c.body || '');
  body.addEventListener('click', () => body.classList.toggle('open'));
  const labels = { sent: 'Sent', draft: 'Draft', received: 'Received' };
  return cardShell(c, 'i-mail', status === 'received' ? 'Email received' : 'Email',
    metaNode(h('span', { class: `status-tag ${status}` }, status === 'sent' ? h('span', { class: 'sending' }, h('span', { class: 'fly' }, icon('i-send', 10)), labels.sent) : labels[status] || status)),
    h('div', { class: 'mail' },
      h('div', { class: 'mail-row' }, h('span', null, status === 'received' ? 'From' : 'To'), h('span', null, c.to || '—')),
      h('div', { class: 'mail-row subj' }, h('span', null, 'Subject'), h('span', null, c.subject || '(no subject)')),
      body));
}

/* ------------------------------------------------------------------ *
 * Savings counter
 * ------------------------------------------------------------------ */
let savingsRaf = 0;
function setSavings(cents) {
  const target = num(cents);
  if (target == null) return;
  const pill = $('#savings');
  const amt = $('#savingsAmt');
  const from = S.savingsCents ?? 0;
  S.savingsCents = target;
  if (target <= 0 && pill.hidden) return;
  pill.hidden = false;
  if (target > from) {
    pill.classList.remove('bump');
    void pill.offsetWidth;
    pill.classList.add('bump');
  }
  cancelAnimationFrame(savingsRaf);
  const t0 = performance.now();
  const dur = 900;
  const fmt = (c) => money(c / 100, 'USD', { whole: c % 100 === 0 || c >= 100000 });
  const step = (now) => {
    const k = Math.min(1, (now - t0) / dur);
    const e = 1 - Math.pow(1 - k, 3);
    amt.textContent = fmt(Math.round(from + (target - from) * e));
    if (k < 1) savingsRaf = requestAnimationFrame(step);
  };
  savingsRaf = requestAnimationFrame(step);
}

async function fetchSavings() {
  try {
    const u = new URL(S.url);
    u.protocol = u.protocol === 'wss:' ? 'https:' : 'http:';
    u.pathname = '/api/savings';
    u.search = '';
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 3000);
    const r = await fetch(u.href, { signal: ctrl.signal });
    clearTimeout(timer);
    if (!r.ok) return;
    const j = await r.json();
    const cents = j && (j.total_cents ?? (j.total != null ? Math.round(j.total * 100) : null));
    if (cents != null && S.savingsCents == null) setSavings(cents);
  } catch (_) { /* backend may not expose it yet */ }
}

/* ------------------------------------------------------------------ *
 * Text input / quick actions
 * ------------------------------------------------------------------ */
function sendText(text) {
  text = (text || '').trim();
  if (!text) return;
  ensurePlayback();
  if (S.session === 'idle' && !S.textSession) {
    send({ type: 'start', voice: false });
    S.textSession = true;
    if (S.product) {
      if (wsOpen()) sendPage(true);
      else send({ type: 'page', product: S.product });
    }
  }
  send({ type: 'text', text });
  S.lastTyped = { text, at: Date.now() };
  addLocalUserBubble(text);
  if (S.conn === 'offline') toast('Backend offline — will send when reconnected.', 'err');
}

/* ------------------------------------------------------------------ *
 * Settings / theme
 * ------------------------------------------------------------------ */
function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === 'dark' || theme === 'light') root.dataset.theme = theme;
  else delete root.dataset.theme;
  document.querySelectorAll('[data-theme-opt]').forEach((b) => {
    b.setAttribute('aria-checked', String(b.dataset.themeOpt === (theme || 'system')));
  });
}

function toggleSettings(force) {
  const panel = $('#settings');
  const open = force ?? panel.hidden;
  panel.hidden = !open;
  $('#settingsBtn').setAttribute('aria-expanded', String(open));
  if (open) {
    $('#urlInput').value = S.url;
    updatePermState();
  }
}

async function saveUrl() {
  let v = $('#urlInput').value.trim() || DEFAULT_URL;
  if (/^https?:\/\//i.test(v)) v = v.replace(/^http/i, 'ws');
  if (!/^wss?:\/\//i.test(v)) v = 'ws://' + v;
  try { new URL(v); } catch (_) { toast('That URL looks invalid', 'err'); return; }
  S.url = v;
  $('#urlInput').value = v;
  await chrome.storage.local.set({ backendUrl: v });
  if (S.session !== 'idle') stopSession();
  S.queue = [];
  reconnectNow();
  fetchSavings();
  toggleSettings(false);
  toast('Saved — connecting to ' + v);
}

/* ------------------------------------------------------------------ *
 * Wiring
 * ------------------------------------------------------------------ */
function bindUI() {
  $('#micBtn').addEventListener('click', () => {
    if (S.session === 'idle') startSession();
    else stopSession();
  });

  $('#statusPill').addEventListener('click', () => {
    if (S.conn === 'offline') { reconnectNow(); fetchSavings(); }
  });

  $('#settingsBtn').addEventListener('click', () => toggleSettings());
  $('#urlSave').addEventListener('click', saveUrl);
  $('#urlInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') saveUrl(); });
  document.querySelectorAll('[data-theme-opt]').forEach((b) => b.addEventListener('click', () => {
    const t = b.dataset.themeOpt;
    applyTheme(t);
    chrome.storage.local.set({ theme: t });
  }));
  $('#micPermBtn').addEventListener('click', openPermissionTab);
  $('#micBannerBtn').addEventListener('click', openPermissionTab);

  const input = $('#textInput');
  const sendBtn = $('#sendBtn');
  input.addEventListener('input', () => { sendBtn.disabled = !input.value.trim(); });
  $('#composer').addEventListener('submit', (e) => {
    e.preventDefault();
    sendText(input.value);
    input.value = '';
    sendBtn.disabled = true;
  });
  $('#quick').addEventListener('click', (e) => {
    const b = e.target.closest('[data-text]');
    if (b) sendText(b.dataset.text);
  });

  $('#clearCards').addEventListener('click', () => {
    S.cards.forEach((el) => el.remove());
    S.cards.clear();
    S.tools.forEach((el) => el.remove());
    S.tools.clear();
    $('#activity').hidden = true;
    $('#insightsSection').hidden = true;
    updateCompact();
    updateStageText();
  });

  $('#productImg').addEventListener('error', (e) => { e.target.removeAttribute('src'); });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#settings').hidden) toggleSettings(false);
  });
}

function bindChrome() {
  chrome.tabs.onActivated.addListener(({ windowId }) => {
    if (S.windowId == null || windowId === S.windowId) scheduleRefresh(50);
  });
  chrome.tabs.onUpdated.addListener((tabId, info) => {
    if (tabId !== S.tabId) return;
    if (info.url || info.status === 'complete') scheduleRefresh(info.status === 'complete' ? 200 : 600);
  });
  chrome.windows.onFocusChanged.addListener(() => scheduleRefresh(100));

  chrome.runtime.onMessage.addListener((msg, sender) => {
    if (!msg) return;
    if (msg.type === 'sl:product' && sender.tab && sender.tab.id === S.tabId) {
      setProduct(msg.product || null);
    } else if (msg.type === 'sl:mic-granted') {
      updatePermState('granted');
      showMicBanner('ready');
    }
  });
}

async function init() {
  bindUI();
  bindChrome();
  try {
    const st = await chrome.storage.local.get(['backendUrl', 'theme']);
    if (st.backendUrl) S.url = st.backendUrl;
    applyTheme(st.theme || 'system');
  } catch (_) { applyTheme('system'); }
  try {
    // Demo/recording mode: sidepanel.html?attach=amazon opened as a standalone window follows the window
    // showing that site instead of its own.
    const attach = new URLSearchParams(location.search).get('attach');
    const [shop] = attach ? await chrome.tabs.query({ url: `*://*.${attach}.com/*` }) : [];
    S.windowId = shop ? shop.windowId : (await chrome.windows.getCurrent()).id;
  } catch (_) { /* ignore */ }
  renderProduct(false);
  renderStatus();
  setSession('idle');
  connect();
  fetchSavings();
  refreshActiveTab();
}

window.addEventListener('pagehide', () => {
  if (S.session !== 'idle') { try { rawSend({ type: 'stop' }); } catch (_) { /* ignore */ } }
});

init();
