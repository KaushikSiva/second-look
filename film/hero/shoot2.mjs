import { chromium } from 'playwright'; import path from 'node:path';
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 2400, height: 1350 } });
await p.goto('file://' + path.resolve('hero/product.html')); await p.waitForTimeout(1000);
await p.screenshot({ path: 'hero/second-look-product.jpg', type: 'jpeg', quality: 92 }); await b.close();
