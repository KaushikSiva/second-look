// Second Look — one-time microphone permission page.
'use strict';

const setState = (s) => { document.body.dataset.state = s; };

async function request() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    stream.getTracks().forEach((t) => t.stop());
    setState('ok');
    try { await chrome.runtime.sendMessage({ type: 'sl:mic-granted' }); } catch (_) { /* panel may be closed */ }
  } catch (err) {
    setState('err');
    const msg = document.getElementById('errMsg');
    if (err && err.name === 'NotFoundError') msg.textContent = 'No microphone was found. Plug one in and try again.';
  }
}

async function closeTab() {
  try {
    const tab = await chrome.tabs.getCurrent();
    if (tab && tab.id != null) { await chrome.tabs.remove(tab.id); return; }
  } catch (_) { /* fall through */ }
  window.close();
}

document.getElementById('grant').addEventListener('click', request);
document.getElementById('retry').addEventListener('click', request);
document.getElementById('back').addEventListener('click', closeTab);

// Prompt immediately; the button remains as a fallback if the prompt was dismissed.
(async () => {
  try {
    const st = await navigator.permissions.query({ name: 'microphone' });
    if (st.state === 'granted') { setState('ok'); chrome.runtime.sendMessage({ type: 'sl:mic-granted' }).catch(() => {}); return; }
  } catch (_) { /* permissions API may not support microphone */ }
  request();
})();
