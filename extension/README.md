# Second Look — Chrome extension

Voice shopping copilot side panel (Chrome MV3, vanilla JS, no build step). Protocol: see `../SPEC.md`.

## Load it

1. Start the backend (default `ws://localhost:8000/ws`).
2. Open `chrome://extensions`, turn on **Developer mode**.
3. Click **Load unpacked** and pick this `extension/` folder.
4. Pin **Second Look**, open an Amazon product page (`amazon.com/dp/...`) and click the toolbar icon. The side panel opens.
5. Tap the mic. The first time, Chrome can't show the mic prompt inside a side panel, so a tab opens to ask for it. Click **Allow**, go back to the panel and tap the mic again.

The backend URL is under the gear icon in the panel (saved in `chrome.storage.local`). The status pill shows the connection state; click it to retry when it says Offline.

## What it does

- `content.js` scrapes the product on Amazon (title, price, list price, rating, review count, ASIN, image, bullets, review snippets, coupon, model number). On Best Buy, Walmart, Target and other sites it reads JSON-LD, microdata or OpenGraph. It pushes updates when the URL or DOM changes. On other sites the panel injects it on demand.
- The side panel streams 16 kHz PCM16 mic audio through an AudioWorklet (`pcm-worklet.js`) and a 1 fps JPEG of the visible tab (max 1024 px wide). It plays 24 kHz PCM16 replies with gapless scheduling and stops playback on `interrupted`.
- Server `card` messages render as verdict, reviews, price chart, stores, alternatives, cost, watch and email cards. A card with an existing `id` replaces the old one. `tool` messages show as activity chips and `savings` updates the header counter.
- You can type questions or tap the quick chips instead of using the mic (sends `{type:"text"}`).

## Notes

- Icons come from `scripts/make_icons.py` (stdlib only): `python3 scripts/make_icons.py`.
- Screenshots don't work on `chrome://` pages or the Chrome Web Store; those frames are skipped.
- On load the panel also tries `GET /api/savings` (`{total_cents}`) on the same host to seed the savings counter.
