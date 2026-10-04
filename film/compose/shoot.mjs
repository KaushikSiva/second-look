import { chromium } from 'playwright';
import path from 'node:path';
const shots = {
  problem: 's=problem', title: 's=title', term: 's=term',
  inst_a: 's=inst', inst_b: 's=inst&ik=STEP 3&it=Load unpacked, choose the <i>extension</i> folder',
  live_a: 's=live&lk=LIVE&lt=A real session on Amazon, asked out loud',
  live_b: 's=live&lk=RESEARCH&lt=Reviews, price memory, other stores, alternatives',
  live_c: 's=live&lk=VERDICT&lt=One honest answer, with its confidence',
  live_d: 's=live&lk=PRICE WATCH&lt=It keeps working after you close the tab',
};
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
for (const [k, qs] of Object.entries(shots)) {
  await p.goto('file://' + path.resolve('compose/cards.html') + '?' + qs);
  await p.waitForTimeout(400);
  await p.screenshot({ path: `compose/${k}.png` });
}
await b.close();
