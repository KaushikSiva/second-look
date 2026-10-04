// Second Look — background service worker.
// Opens the side panel on toolbar click and caches/relays the product context
// that content.js scrapes from each tab.
'use strict';

function enablePanel() {
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch((e) => console.warn('[second-look] setPanelBehavior', e));
  }
}

chrome.runtime.onInstalled.addListener(enablePanel);
chrome.runtime.onStartup.addListener(enablePanel);
enablePanel();

const key = (tabId) => 'product:' + tabId;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg !== 'object') return;

  // Content script pushed a fresh product for its tab. The side panel receives the
  // same broadcast directly; we cache it so the panel can render instantly on tab switch.
  if (msg.type === 'sl:product' && sender.tab && sender.tab.id != null) {
    const tabId = sender.tab.id;
    chrome.storage.session.set({ [key(tabId)]: msg.product || null }).catch(() => {});
    try {
      chrome.action.setBadgeBackgroundColor({ tabId, color: '#7C6CFF' });
      chrome.action.setBadgeText({ tabId, text: msg.product ? ' ' : '' });
    } catch (_) { /* tab may be gone */ }
    return;
  }

  if (msg.type === 'sl:getCachedProduct' && msg.tabId != null) {
    chrome.storage.session.get(key(msg.tabId))
      .then((r) => sendResponse({ product: r[key(msg.tabId)] || null }))
      .catch(() => sendResponse({ product: null }));
    return true; // async response
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(key(tabId)).catch(() => {});
});
