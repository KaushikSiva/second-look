# Second Look — architecture & wire protocol

Voice shopping copilot for Amazon/e-commerce. Chrome MV3 side panel ⇄ Python (FastAPI) backend ⇄ Gemini 3.8 Live.
The backend owns the Gemini Live session (keys never ship in the extension) and runs all tools.

```
extension/ (MV3, vanilla JS, no build step)
  sidepanel.html/.js/.css  mic (16 kHz PCM16) + 1 fps tab screenshots → WS; plays 24 kHz PCM16 audio; renders cards
  content.js               scrapes product page → {type:"page"} context
  background.js            opens side panel on action click, relays page context
  permission.html/.js      one-time mic permission tab (side panels can't show the prompt)
backend/ (FastAPI)
  app/main.py              /ws session bridge, REST: /api/watchlist, /api/savings, /api/agentmail/webhook, /health
  app/live.py              Gemini Live session + tool dispatch (NON_BLOCKING tools)
  app/research.py          research_product fan-out: reviews ‖ price ‖ alternatives → JEV verdict
  app/db.py                Neon (products, price_history, watchlist, purchases, savings, events)
```

## WebSocket `ws://<host>/ws`

Client → server (JSON text frames):
| type | fields |
|---|---|
| `start` | `{voice?: bool}` begin Gemini session |
| `audio` | `{data: base64 PCM16 LE 16 kHz mono}` |
| `frame` | `{data: base64 JPEG}` ≤ 1/s |
| `page` | `{product: Product}` whenever the active tab's product changes |
| `text` | `{text}` typed message |
| `stop` | end session |

Server → client:
| type | fields |
|---|---|
| `status` | `{state: "connecting"|"live"|"closed"|"error", message?}` |
| `audio` | `{data: base64 PCM16 LE 24 kHz mono}` |
| `transcript` | `{role: "user"|"agent", text, final: bool}` (append deltas until final) |
| `interrupted` | `{}` stop playback immediately |
| `tool` | `{id, name, state: "running"|"done"|"error", label}` activity chips |
| `card` | `{card: Card}` (replace existing card with same `id`) |
| `savings` | `{total_cents}` |

### Product (from content.js)
`{url, site, asin?, title, brand?, price, currency, list_price?, rating?, review_count?, image?, model?, bullets?: [], review_snippets?: [], coupon?: string}`

### Card kinds (`card.kind`)
- `verdict` `{id, kind, verdict: "BUY_NOW"|"WAIT"|"SKIP"|"BUY_ALTERNATIVE", confidence, headline, reasons: [str], probabilities:{}}`
- `reviews` `{id, kind, shown_rating, real_rating, pros:[str], cons:[str], incentivized_pct?, sources:[{title,url}]}`
- `price` `{id, kind, current, low, avg, high, fake_discount: bool, list_price?, history:[{t, price}], note}`
- `stores` `{id, kind, offers:[{store, price, total?, url, in_stock?, note?}], best?: {store, saving}}`
- `alternatives` `{id, kind, items:[{title, price?, why, url}]}`
- `cost` `{id, kind, yearly_extra, items:[str]}`
- `watch` `{id, kind, title, target_price, current}`
- `email` `{id, kind, to, subject, body, status: "sent"|"draft"|"received"}`
