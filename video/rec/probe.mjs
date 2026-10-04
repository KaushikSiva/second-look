import { chromium } from 'playwright';
const ctx = await chromium.launchPersistentContext('/private/tmp/claude-501/sl-profile', {
  channel: 'chromium', headless: true, viewport: { width: 1280, height: 800 },
  args: [`--disable-extensions-except=${process.env.EXT}`, `--load-extension=${process.env.EXT}`],
});
let [sw] = ctx.serviceWorkers(); if (!sw) sw = await ctx.waitForEvent('serviceworker');
console.log('ext id', sw.url().split('/')[2]);
const page = ctx.pages()[0] || await ctx.newPage();
await page.goto('https://www.amazon.com/dp/B07VVK39F7', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(3000);
console.log('title:', await page.title());
console.log('price:', await page.locator('.a-price .a-offscreen').first().textContent().catch(()=>null));
await page.screenshot({ path: 'probe.png' });
await ctx.close();
