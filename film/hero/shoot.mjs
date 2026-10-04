import { chromium } from 'playwright';
import path from 'node:path';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 2400, height: 1260 } });
await p.goto('file://' + path.resolve('hero/hero.html'));
await p.waitForTimeout(1500);
await p.screenshot({ path: 'hero/second-look-hero.png' });
await b.close();
