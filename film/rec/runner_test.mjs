import { chromium } from 'playwright'; import path from 'node:path'; import fs from 'node:fs';
const EXT = path.resolve('../extension'); const P = '/private/tmp/claude-501/sl-rt'; fs.rmSync(P, { recursive: true, force: true });
const ctx = await chromium.launchPersistentContext(P, { channel: 'chromium', headless: true, viewport: { width: 1280, height: 800 },
  args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`, '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'] });
let [sw] = ctx.serviceWorkers(); if (!sw) sw = await ctx.waitForEvent('serviceworker');
const shop = ctx.pages()[0]; await shop.goto('https://www.amazon.com/dp/B07VVK39F7', { waitUntil: 'domcontentloaded' }); await shop.waitForTimeout(2500);
const pp = ctx.waitForEvent('page');
await sw.evaluate(() => chrome.windows.create({ url: chrome.runtime.getURL('sidepanel.html?attach=amazon'), width: 440, height: 800 }));
const panel = await pp; await panel.setViewportSize({ width: 440, height: 800 }); await panel.emulateMedia({ colorScheme: 'dark' });
panel.on('pageerror', (e) => console.log('ERR', e.message));
await panel.waitForTimeout(2500);
await panel.fill('#textInput', 'Should I buy this?'); await panel.press('#textInput', 'Enter');
await panel.waitForSelector('.runner', { timeout: 20000 }); await panel.waitForTimeout(2500);
await panel.screenshot({ path: 'rec/runner_a.png' });
await panel.waitForTimeout(1200);
await panel.locator('.runner').screenshot({ path: 'rec/runner_b.png' });
await panel.waitForSelector('article.card.verdict', { timeout: 90000 }); await panel.waitForTimeout(1500);
console.log('runner hidden after verdict:', await panel.locator('.runner').isHidden());
await ctx.close();
