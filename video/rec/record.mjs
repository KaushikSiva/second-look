// Records the real extension against the live backend: Amazon tab (left) + Second Look panel (right), captured as
// timestamped screenshots, plus an events log so the film can cut shots on real moments.
// Usage: EXT=../../extension node record.mjs
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const OUT = path.resolve('frames');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });
const events = [];
const t0 = Date.now();
const mark = (name) => { events.push({ name, t: (Date.now() - t0) / 1000, wall: Date.now() / 1000 }); console.log(name, events.at(-1).t); };

const ctx = await chromium.launchPersistentContext('/private/tmp/claude-501/sl-profile', {
  channel: 'chromium', headless: true, viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1,
  args: [`--disable-extensions-except=${process.env.EXT}`, `--load-extension=${process.env.EXT}`],
});
let [sw] = ctx.serviceWorkers(); if (!sw) sw = await ctx.waitForEvent('serviceworker');
const shop = ctx.pages()[0] || await ctx.newPage();
await shop.goto(process.env.URL || 'https://www.amazon.com/dp/B07VVK39F7', { waitUntil: 'domcontentloaded' });
await shop.waitForTimeout(2500);
// dismiss the sign-in flyout if present
await shop.mouse.click(640, 600).catch(() => {});

const panelP = ctx.waitForEvent('page');
await sw.evaluate(() => chrome.windows.create({ url: chrome.runtime.getURL('sidepanel.html?attach=amazon'), width: 440, height: 800 }));
const panel = await panelP;
await panel.setViewportSize({ width: 440, height: 800 });
await panel.emulateMedia({ colorScheme: 'dark' });
await panel.waitForLoadState('domcontentloaded');

let shooting = true, n = 0;
(async () => {
  while (shooting) {
    const t = (Date.now() - t0) / 1000;
    try {
      const [a, b] = await Promise.all([shop.screenshot({ type: 'jpeg', quality: 85 }), panel.screenshot({ type: 'jpeg', quality: 90 })]);
      const id = String(n++).padStart(5, '0');
      fs.writeFileSync(`${OUT}/${id}_${t.toFixed(3)}_shop.jpg`, a);
      fs.writeFileSync(`${OUT}/${id}_${t.toFixed(3)}_panel.jpg`, b);
    } catch (e) { /* page busy */ }
    await new Promise(r => setTimeout(r, 90));
  }
})();

// Follow the story: smoothly scroll each newly arrived card into view (what a viewer would look at).
const seen = new Set();
let following = true;
(async () => {
  while (following) {
    try {
      const ids = await panel.evaluate(() => [...document.querySelectorAll('article[data-id], [data-id].card')].map(e => e.dataset.id));
      for (const id of ids) if (!seen.has(id)) {
        seen.add(id);
        await panel.evaluate((id) => document.querySelector(`[data-id="${id}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), id);
        mark(`card_${id}`);
        await panel.waitForTimeout(1600);
      }
    } catch (e) { /* navigating */ }
    await panel.waitForTimeout(250);
  }
})();

const ask = async (q, name) => {
  await panel.click('#textInput');
  mark(`${name}_typing`);
  await panel.type('#textInput', q, { delay: 55 });
  await panel.waitForTimeout(300);
  mark(name);
  await panel.press('#textInput', 'Enter');
};

await panel.waitForTimeout(3500);
mark('panel_ready');
await ask('Should I buy this?', 'ask');
await panel.waitForSelector('article.card.verdict', { timeout: 120000 });
mark('verdict');
await panel.waitForTimeout(16000);            // let the agent speak the verdict
mark('verdict_spoken');
await panel.evaluate(() => document.querySelector('article.card.verdict')?.scrollIntoView({ block: 'start' }));
await panel.waitForTimeout(2500);
await ask('Watch it for me and tell me if it drops under $75', 'watch');
await panel.waitForFunction(() => [...document.querySelectorAll('[data-id]')].some(e => e.dataset.id.startsWith('watch')), null, { timeout: 60000 })
  .catch(() => console.log('no watch card'));
mark('watch_card');
await panel.waitForTimeout(9000);
mark('end');
following = false;
shooting = false;
await new Promise(r => setTimeout(r, 400));
fs.writeFileSync('events.json', JSON.stringify(events, null, 2));
await ctx.close();
