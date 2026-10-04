# Second Look — demo film (≈2:30, 16:9)

Narrator: Kaushik (Cutroom ElevenLabs voice `CUTROOM_ELEVEN_VOICE`, same as previous Cutroom films).
Style: clean product film — dark UI palette (#0B0D12 bg, #7C9CFF accent, #3DDC97 buy, #FFB547 wait, #FF6B6B skip),
Inter typography, eased motion. Screen recordings composited in a soft device frame.

| # | t | kind | visual | narration |
|---|---|---|---|---|
| 1 | 0:00–0:07 | graphic (hyperframes title_card) | "Second Look" logo reveal, subtitle "a voice shopping agent that lives in your browser" | Hi, I'm Kaushik, and this is Second Look. |
| 2 | 0:07–0:20 | graphic (kinetic text) | "$129 — was $199 — 35% off!" → strike-through "fake", "4.6★" → "3.9★ real" | Every day we make dozens of buying decisions on pages that are designed to rush us, with discounts that are not quite real and reviews that are not quite honest. |
| 3 | 0:20–0:45 | screen | Amazon product page, side panel opens, mic ring pulses, "Should I buy this?" | So I built a friend who sits beside you while you shop. You open the side panel and simply ask, out loud, whether the thing in front of you is worth it. |
| 4 | 0:45–1:15 | screen | activity chips spin, cards stream in: price chart with FAKE DISCOUNT, reviews 4.6→3.9, stores table w/ Kernel verified, alternatives | Gemini 3.8 Live hears the question and sees the page, then starts the research in the background while it keeps talking with you. Exa reads what real owners say on Reddit, Neon remembers every price it has ever seen, and a Kernel cloud browser opens the other stores to check the live price. |
| 5 | 1:15–1:30 | screen | verdict card "WAIT" with confidence bar, agent voice audible | Jev, a fast decision model from TypeSafe, weighs all of that into a single honest verdict, with a confidence you can see. |
| 6 | 1:30–1:50 | screen | "Watch it under $85" → watch card; later email card "Price drop" + savings counter ticks up | And it keeps working after you close the tab. Ask it to watch a price and it will email you from its own AgentMail inbox the moment the price drops. |
| 7 | 1:50–2:10 | graphic (motion_canvas architecture) | Side panel → FastAPI on Fly.io → Gemini Live; tools fan out to Exa, Kernel, Neon, AgentMail, Jev | Under the hood, a Python backend holds the live session, so no keys ever ship in the extension, and every tool runs without interrupting the conversation. |
| 8 | 2:10–2:30 | graphic (data_callout + end card) | "💰 $212 saved" → "Second Look — before you buy, take a second look." | Shopping should not be a contest you are set up to lose. Before you buy, take a second look. |
