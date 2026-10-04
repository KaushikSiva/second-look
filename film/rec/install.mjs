// Records the real install flow in Chromium: chrome://extensions -> Developer mode -> Load unpacked -> card appears.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const EXT = path.resolve('extension');
const OUT = path.resolve('film/rec/install');
fs.rmSync(OUT, { recursive: true, force: true }); fs.mkdirSync(OUT, { recursive: true });
const PROFILE = '/private/tmp/claude-501/sl-install-profile';
fs.rmSync(PROFILE, { recursive: true, force: true });
const events = []; const t0 = Date.now();
const mark = (n) => { events.push({ name: n, t: (Date.now() - t0) / 1000 }); console.log(n, events.at(-1).t); };

const ctx = await chromium.launchPersistentContext(PROFILE, {
  channel: 'chromium', headless: true, viewport: { width: 1280, height: 800 },
  args: ['--enable-unsafe-extension-debugging'],
});
const page = ctx.pages()[0] || await ctx.newPage();
await page.emulateMedia({ colorScheme: 'dark' });
let n = 0;
const cdp = await ctx.newCDPSession(page);
cdp.on('Page.screencastFrame', async ({ data, sessionId }) => {
  fs.writeFileSync(`${OUT}/${String(n++).padStart(6, '0')}_${((Date.now() - t0) / 1000).toFixed(3)}.jpg`, Buffer.from(data, 'base64'));
  cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {});
});
await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 90, maxWidth: 1280, maxHeight: 800 });

await page.goto('chrome://extensions');
mark('extensions_page');
await page.waitForTimeout(2500);
// Developer mode toggle lives in the shadow DOM; Playwright pierces it.
const box = async (sel) => (await page.locator(sel).boundingBox());
const devToggle = page.locator('#devMode');
const b1 = await devToggle.boundingBox();
await page.mouse.move(640, 400); await page.mouse.move(b1.x + b1.width / 2, b1.y + b1.height / 2, { steps: 25 });
mark('cursor_dev');
await page.waitForTimeout(500);
await devToggle.click();
mark('dev_on');
await page.waitForTimeout(2000);
const load = page.locator('#loadUnpacked');
const b2 = await load.boundingBox();
await page.mouse.move(b2.x + b2.width / 2, b2.y + b2.height / 2, { steps: 25 });
mark('cursor_load');
await page.waitForTimeout(700);
mark('load_click');
// The folder picker is a native dialog; select extension/ through the same backend call the picker resolves to.
const bcdp = await ctx.browser()?.newBrowserCDPSession?.() ?? null;
let id;
try {
  const s = bcdp || await ctx.newCDPSession(page);
  ({ id } = await s.send('Extensions.loadUnpacked', { path: EXT }));
console.log('loaded id', id); } catch (e) { console.error('loadUnpacked failed', e.message); }
mark('loaded');
await page.waitForTimeout(600);
await page.reload();
mark('reloaded');
await page.waitForTimeout(1200);
await page.mouse.move(700, 300, { steps: 20 });
await page.waitForTimeout(3000);
fs.writeFileSync(path.join(OUT, '..', 'install_events.json'), JSON.stringify({ events, id }, null, 1));
await cdp.send('Page.stopScreencast');
await ctx.close();
