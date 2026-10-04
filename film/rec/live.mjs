// Records a real Second Look session: real Amazon page + the redesigned side panel against the live local backend.
// The first question is spoken into Chrome's real mic path (fake capture device fed with mic.wav); the follow-up is typed.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve('..');
const EXT = path.join(ROOT, 'extension');
const OUT = path.resolve('rec/live/frames');
fs.rmSync(OUT, { recursive: true, force: true }); fs.mkdirSync(OUT, { recursive: true });
const PROFILE = '/private/tmp/claude-501/sl-live-profile';
fs.rmSync(PROFILE, { recursive: true, force: true });
const events = []; const audio = []; const t0 = Date.now();
const now = () => (Date.now() - t0) / 1000;
const mark = (n, extra) => { events.push({ name: n, t: now(), ...extra }); console.log(n, now().toFixed(2)); };

const ctx = await chromium.launchPersistentContext(PROFILE, {
  channel: 'chromium', headless: true, viewport: { width: 1280, height: 800 },
  args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`,
    '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
    `--use-file-for-fake-audio-capture=${path.resolve('rec/live/mic.wav')}%noloop`,
    '--autoplay-policy=no-user-gesture-required', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows', '--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling'],
});
await ctx.grantPermissions(['microphone']);
let [sw] = ctx.serviceWorkers(); if (!sw) sw = await ctx.waitForEvent('serviceworker');
const extId = sw.url().split('/')[2];

const shop = ctx.pages()[0] || await ctx.newPage();
await shop.goto(process.env.URL || 'https://www.amazon.com/dp/B07VVK39F7', { waitUntil: 'domcontentloaded' });
await shop.waitForTimeout(3000);
await shop.keyboard.press('Escape').catch(() => {});
console.log('title:', await shop.title());

const panelP = ctx.waitForEvent('page');
await sw.evaluate(() => chrome.windows.create({ url: chrome.runtime.getURL('sidepanel.html?attach=amazon'), width: 440, height: 800 }));
const panel = await panelP;
await panel.setViewportSize({ width: 440, height: 800 });
await panel.emulateMedia({ colorScheme: 'dark' });
panel.on('websocket', (ws) => ws.on('framereceived', (f) => {
  try { const m = JSON.parse(f.payload); if (m.type === 'audio') audio.push({ t: now(), data: m.data }); } catch (_) {}
}));
panel.on('console', (m) => { if (m.type() === 'error') console.log('[panel]', m.text()); });

let n = 0;
async function screencast(page, kind, w, h) {
  const cdp = await ctx.newCDPSession(page);
  cdp.on('Page.screencastFrame', async ({ data, sessionId }) => {
    fs.writeFileSync(`${OUT}/${String(n++).padStart(6, '0')}_${now().toFixed(3)}_${kind}.jpg`, Buffer.from(data, 'base64'));
    cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {});
  });
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 90, maxWidth: w, maxHeight: h });
}
await panel.waitForLoadState('domcontentloaded');
await screencast(shop, 'shop', 1280, 800);
await screencast(panel, 'panel', 440, 800);
// keep the shop page repainting a little so its frames stay current
await panel.waitForTimeout(3000);
mark('panel_ready');

// Follow each new card into view.
const seen = new Set(); let following = true;
(async () => {
  while (following) {
    try {
      const ids = await panel.evaluate(() => [...document.querySelectorAll('article[data-id]')].map((e) => e.dataset.id));
      for (const id of ids) if (!seen.has(id)) {
        seen.add(id); mark(`card_${id}`);
        await panel.evaluate((id) => document.querySelector(`[data-id="${id}"]`)?.scrollIntoView({ behavior: 'smooth', block: id === 'verdict' ? 'start' : 'center' }), id);
        await panel.waitForTimeout(id === 'verdict' ? 5000 : 1500);
      }
    } catch (_) {}
    await panel.waitForTimeout(200);
  }
})();

// Spoken question: tap the mic; the fake device starts playing mic.wav (2 s of silence, then the question).
await panel.click('#micBtn');
mark('mic_tap');
await panel.waitForSelector('article.card.verdict', { timeout: 120000 }).catch(() => mark('no_verdict'));
mark('verdict');
await panel.waitForTimeout(22000); // let the agent finish speaking the verdict
// Typed follow-up.
await panel.click('#textInput');
mark('type_watch');
await panel.type('#textInput', 'Watch it and email me if it drops under $70.', { delay: 45 });
await panel.waitForTimeout(400);
await panel.press('#textInput', 'Enter');
mark('ask_watch');
await panel.waitForSelector('article.card.watch', { timeout: 60000 }).catch(() => mark('no_watch'));
mark('watch');
await panel.waitForTimeout(12000);
following = false;
mark('end');
fs.writeFileSync('rec/live/events.json', JSON.stringify(events, null, 1));
fs.writeFileSync('rec/live/audio.json', JSON.stringify(audio));
await ctx.close();
