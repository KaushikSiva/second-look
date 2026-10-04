"""Second Look film: custom motion-graphics sources for Cutroom.

Hyperframes compositions are built with Cutroom's own page shell (hf_templates.page: Inter + GSAP, a paused timeline
registered on window.__timelines["main"]); the architecture diagram is a Motion Canvas TSX scene.
Palette from the script: #0B0D12 bg, #7C9CFF accent, #3DDC97 buy, #FFB547 wait, #FF6B6B skip.
"""
from cutroom.motion.hf_templates import page

W, H = 1920, 1080
# device frame rect shared by the placeholders and the real recordings (leaves the bottom band for captions)
FRAME = {"x": 192, "y": 44, "w": 1536, "h": 864, "r": 22}

BASE_CSS_ = """
:root{--bg:#0B0D12;--acc:#7C9CFF;--buy:#3DDC97;--wait:#FFB547;--skip:#FF6B6B;--fg:#E8ECF4;--mut:#8A93A6;
--card:#141823;--card2:#191E2B;--line:#252B3B}
html,body{background:#0B0D12!important}
#root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:var(--fg);background:var(--bg)}
.bgx{position:absolute;inset:0;background:
  radial-gradient(55% 60% at 50% 38%, rgba(124,156,255,.13), transparent 70%),
  radial-gradient(40% 40% at 85% 95%, rgba(61,220,151,.05), transparent 70%), #0B0D12}
.bgx{inset:-6%}
.center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
"""


ODO_CSS = """
.odo{display:inline-flex;align-items:flex-start;overflow:hidden;height:1em;line-height:1;vertical-align:top}
.odo .dc{display:flex;flex-direction:column;flex-shrink:0;align-self:flex-start}
.odo .dc span{height:1em;line-height:1;display:block;text-align:center}
"""


def odo(prefix: str, value: str) -> str:
    """Odometer markup: one rolling column per digit (deterministic under frame seeking, unlike onUpdate counters)."""
    cols = "".join(f'<span class="dc" id="{prefix}{i}">' + "".join(f"<span>{d % 10}</span>" for d in range(20)) + "</span>"
                   for i, ch in enumerate(value))
    return f'<span class="odo">{cols}</span>'


def odo_js(prefix: str, value: str, at: float, dur: float = 2.0) -> str:
    out = ""
    for i, ch in enumerate(value):
        k = 10 + int(ch)
        out += f"tl.fromTo('#{prefix}{i}', {{yPercent:0}}, {{yPercent:-{k * 5}, duration:{dur + 0.25 * i:.2f}, ease:'power3.out'}}, {at});\n"
    return out

BASE_CSS = BASE_CSS_ + ODO_CSS

MARK_SVG = """<svg class="mark" viewBox="0 0 260 180" width="{w}" height="{h}">
  <circle id="{p}r1" cx="100" cy="90" r="70" fill="none" stroke="#E8ECF4" stroke-opacity=".55" stroke-width="9"
          stroke-dasharray="440" stroke-dashoffset="440" stroke-linecap="round" transform="rotate(-90 100 90)"/>
  <circle id="{p}r2" cx="160" cy="90" r="70" fill="none" stroke="#7C9CFF" stroke-width="9"
          stroke-dasharray="440" stroke-dashoffset="440" stroke-linecap="round" transform="rotate(-90 160 90)"/>
  <circle id="{p}dot" cx="160" cy="90" r="16" fill="#7C9CFF"/>
</svg>"""


# slow ambient drift of the backdrop so held frames never read as frozen
DRIFT_JS = "\ntl.fromTo('.bgx', {x:-40, y:10, scale:1}, {x:40, y:-10, scale:1.06, duration:D, ease:'sine.inOut'}, 0);\n"


def _mark(prefix: str, w=260, h=180) -> str:
    return MARK_SVG.format(p=prefix, w=w, h=h)


def _mark_js(prefix: str, at: float) -> str:
    return f"""
tl.to('#{prefix}r1', {{strokeDashoffset:0, duration:1.0, ease:'power2.inOut'}}, {at});
tl.fromTo('#{prefix}r2', {{x:-60}}, {{x:0, duration:1.1, ease:'power3.out'}}, {at + 0.55});
tl.to('#{prefix}r2', {{strokeDashoffset:0, duration:1.0, ease:'power2.inOut'}}, {at + 0.55});
tl.fromTo('#{prefix}dot', {{scale:0, transformOrigin:'50% 50%'}}, {{scale:1, duration:0.6, ease:'back.out(2)'}}, {at + 1.3});
"""


# ------------------------------------------------------------------ s01 title
def title_html(dur: float) -> str:
    css = BASE_CSS + """
.word{font-weight:700;font-size:150px;letter-spacing:-0.035em;line-height:1;margin-top:34px;display:flex;gap:36px}
.word .m{overflow:hidden;display:inline-block;padding-bottom:12px}
.word .w{display:inline-block}
.word .acc{color:var(--acc)}
.sub{margin-top:26px;font-size:40px;font-weight:500;color:var(--mut);letter-spacing:-0.01em}
.chip{margin-top:44px;font-size:22px;font-weight:600;color:var(--acc);border:1.5px solid rgba(124,156,255,.45);
      border-radius:999px;padding:10px 22px;letter-spacing:.06em;text-transform:uppercase}
#grp{transform-origin:50% 50%}
"""
    body = f"""<div class="bgx"></div>
<div class="center" id="grp">
  {_mark('t')}
  <div class="word"><span class="m"><span class="w">Second</span></span><span class="m"><span class="w acc">Look</span></span></div>
  <div class="sub" id="sub">a voice shopping agent that lives in your browser</div>
  <div class="chip" id="chip">Chrome extension &middot; Gemini 3.8 Live</div>
</div>"""
    js = _mark_js("t", 0.2) + """
tl.from('.word .w', {yPercent:110, duration:0.9, ease:'power4.out', stagger:0.14}, 1.1);
tl.from('#sub', {opacity:0, y:24, duration:0.8, ease:'power2.out'}, 1.9);
tl.from('#chip', {opacity:0, y:16, duration:0.7, ease:'power2.out'}, 2.4);
tl.fromTo('#grp', {scale:1}, {scale:1.035, duration:D, ease:'sine.inOut'}, 0);
tl.to('#grp', {opacity:0, duration:0.45, ease:'power1.in'}, D - 0.5);
"""
    return page(W, H, dur, body, css, js + DRIFT_JS)


# ------------------------------------------------------------------ s02 kinetic text: fake discount, inflated rating
def kinetic_html(dur: float, stamp_at: float = 5.0, flip_at: float = 9.2) -> str:
    stage2 = stamp_at + 2.2
    css = BASE_CSS + """
.stage{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
.price{display:flex;align-items:center;gap:56px}
.now{font-size:230px;font-weight:700;letter-spacing:-0.05em;line-height:1}
.col{display:flex;flex-direction:column;gap:22px;align-items:flex-start}
.was{position:relative;font-size:68px;font-weight:500;color:var(--mut)}
.strike{position:absolute;left:-6px;right:-6px;top:52%;height:7px;background:var(--skip);border-radius:4px;transform-origin:0 50%;transform:scaleX(0)}
.badge{font-size:50px;font-weight:700;background:var(--skip);color:#0B0D12;padding:8px 22px;border-radius:14px}
.stamp{position:absolute;left:50%;top:67%;transform:translate(-50%,-50%) rotate(-8deg);font-size:84px;font-weight:800;
       letter-spacing:.12em;color:var(--skip);border:8px solid var(--skip);border-radius:18px;padding:4px 34px;opacity:0}
.note{position:absolute;left:0;right:0;top:77%;text-align:center;font-size:34px;color:var(--mut);opacity:0}
.rate{display:flex;flex-direction:column;align-items:center}
.lbl{font-size:30px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--mut);height:44px;position:relative;width:900px}
.lbl > span{position:absolute;left:0;right:0;text-align:center}
.num{position:relative;height:250px;width:900px;font-size:230px;font-weight:700;letter-spacing:-0.04em;line-height:250px}
.num > span{position:absolute;left:0;right:0;text-align:center}
.star{color:#F5C451}
.real{color:var(--wait)}
.real .star{color:var(--wait)}
.tag{margin-top:28px;font-size:34px;font-weight:600;color:#0B0D12;background:var(--wait);border-radius:999px;padding:8px 26px;opacity:0}
"""
    body = """<div class="bgx"></div>
<div class="stage" id="s1">
  <div class="price">
    <div class="now" id="now">$129</div>
    <div class="col"><div class="was" id="was">was $199<div class="strike" id="strike"></div></div>
      <div class="badge" id="badge">35% off!</div></div>
  </div>
  <div class="stamp" id="stamp">FAKE</div>
  <div class="note" id="note">It was never really sold at $199.</div>
</div>
<div class="stage" id="s2" style="opacity:0">
  <div class="rate">
    <div class="lbl"><span id="l1">listed rating</span><span id="l2" style="opacity:0">honest reviews only</span></div>
    <div class="num"><span id="n1">4.6<span class="star">&#9733;</span></span><span id="n2" class="real" style="opacity:0">3.9<span class="star">&#9733;</span></span></div>
    <div class="tag" id="tag">real</div>
  </div>
</div>"""
    js = f"""
tl.from('#now', {{opacity:0, y:50, duration:0.8, ease:'power3.out'}}, 0.3);
tl.from('#was', {{opacity:0, x:40, duration:0.7, ease:'power3.out'}}, 0.75);
tl.from('#badge', {{opacity:0, scale:0.6, duration:0.6, ease:'back.out(2.2)'}}, 1.1);
tl.to('#badge', {{scale:1.06, duration:0.5, ease:'sine.inOut', yoyo:true, repeat:5}}, 1.8);
tl.to('#strike', {{scaleX:1, duration:0.45, ease:'power2.inOut'}}, {stamp_at - 0.3});
tl.to('#badge', {{background:'#3a2a30', color:'#8A93A6', duration:0.4}}, {stamp_at});
tl.to('#now', {{color:'#8A93A6', duration:0.4}}, {stamp_at});
tl.fromTo('#stamp', {{opacity:0, scale:1.7}}, {{opacity:1, scale:1, duration:0.35, ease:'power4.in'}}, {stamp_at});
tl.to('#root', {{x:8, duration:0.05, yoyo:true, repeat:3}}, {stamp_at + 0.35});
tl.to('#note', {{opacity:1, duration:0.5}}, {stamp_at + 0.6});
tl.to('#s1', {{opacity:0, y:-60, duration:0.6, ease:'power2.in'}}, {stage2});
tl.fromTo('#s2', {{opacity:0, y:60}}, {{opacity:1, y:0, duration:0.7, ease:'power3.out'}}, {stage2 + 0.4});
tl.to('#n1', {{y:-120, opacity:0, duration:0.5, ease:'power2.in'}}, {flip_at});
tl.fromTo('#n2', {{y:120, opacity:0}}, {{y:0, opacity:1, duration:0.6, ease:'power3.out'}}, {flip_at + 0.25});
tl.to('#l1', {{opacity:0, duration:0.3}}, {flip_at});
tl.to('#l2', {{opacity:1, duration:0.4}}, {flip_at + 0.3});
tl.fromTo('#tag', {{opacity:0, scale:0.6}}, {{opacity:1, scale:1, duration:0.5, ease:'back.out(2)'}}, {flip_at + 0.6});
tl.to('#s2', {{opacity:0, duration:0.4}}, D - 0.45);
"""
    return page(W, H, dur, body, css, js + DRIFT_JS)


# ------------------------------------------------------------------ s08 savings callout + end card
def endcard_html(dur: float, amount: int = 212, end_at: float = 4.4) -> str:
    css = BASE_CSS + """
.stage{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.amt{font-size:240px;font-weight:700;letter-spacing:-0.05em;color:var(--buy);line-height:1}
.saved{font-size:56px;font-weight:600;margin-top:10px}
.ctx{font-size:32px;color:var(--mut);margin-top:22px}
.word{font-weight:700;font-size:130px;letter-spacing:-0.035em;line-height:1;margin-top:26px}
.word .acc{color:var(--acc)}
.tagline{margin-top:34px;font-size:46px;font-weight:500;color:var(--fg);letter-spacing:-0.01em}
.foot{position:absolute;bottom:70px;left:0;right:0;text-align:center;font-size:24px;color:var(--mut);letter-spacing:.08em;text-transform:uppercase}
"""
    body = f"""<div class="bgx"></div>
<div class="stage" id="s1">
  <div class="amt">${odo("ea", str(amount))}</div>
  <div class="saved">saved</div>
  <div class="ctx">by waiting for real price drops</div>
</div>
<div class="stage" id="s2" style="opacity:0">
  {_mark('e', 208, 144)}
  <div class="word" id="wm">Second <span class="acc">Look</span></div>
  <div class="tagline" id="tagline">Before you buy, take a second look.</div>
  <div class="foot" id="foot">Chrome extension &middot; Gemini 3.8 Live &middot; Exa &middot; Kernel &middot; Neon &middot; AgentMail &middot; Jev</div>
</div>"""
    js = f"""
tl.from('#s1', {{opacity:0, scale:0.92, duration:0.6, ease:'power3.out'}}, 0.1);
""" + odo_js('ea', str(amount), 0.3) + f"""
tl.from('.saved,.ctx', {{opacity:0, y:20, duration:0.6, stagger:0.15}}, 1.2);
tl.to('#s1', {{opacity:0, scale:1.04, duration:0.5, ease:'power2.in'}}, {end_at - 0.5});
tl.to('#s2', {{opacity:1, duration:0.5}}, {end_at});
""" + _mark_js("e", end_at) + f"""
tl.from('#wm', {{opacity:0, y:30, duration:0.8, ease:'power3.out'}}, {end_at + 0.5});
tl.from('#tagline', {{opacity:0, y:20, duration:0.8, ease:'power2.out'}}, {end_at + 1.0});
tl.from('#foot', {{opacity:0, duration:1.0}}, {end_at + 2.4});
tl.to('#s2', {{opacity:0, duration:1.0, ease:'power1.in'}}, D - 1.1);
"""
    return page(W, H, dur, body, css, js + DRIFT_JS)


# ------------------------------------------------------------------ s03-s06 placeholders in the device frame
PANEL_CONTENT = {
    "ask": """
  <div class="mic-wrap"><div class="ring" id="ring1"></div><div class="ring" id="ring2"></div><div class="mic" id="mic">
    <svg viewBox="0 0 24 24" width="54" height="54"><path fill="#0B0D12" d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z"/></svg></div></div>
  <div class="status" id="status">Listening&hellip;</div>
  <div class="bubble user" id="q">Should I buy this?</div>
  <div class="bubble agent" id="a">Let me take a second look at this one for you.</div>""",
    "cards": """
  <div class="chips">
    <div class="chip c" id="ch1"><i></i>Exa &middot; owner reviews</div>
    <div class="chip c" id="ch2"><i></i>Neon &middot; price history</div>
    <div class="chip c" id="ch3"><i></i>Kernel &middot; live stores</div>
  </div>
  <div class="card k" id="k1"><div class="kh">Price history <b class="red">FAKE DISCOUNT</b></div>
    <svg viewBox="0 0 360 70" width="100%" height="70"><polyline fill="none" stroke="#7C9CFF" stroke-width="3"
      points="0,40 40,42 80,38 120,41 160,39 200,40 240,12 260,40 300,41 360,40"/></svg>
    <div class="ks">Usual price $129 &middot; &ldquo;was $199&rdquo; for 2 days</div></div>
  <div class="card k" id="k2"><div class="kh">Reviews <b class="amb">4.6 &rarr; 3.9&#9733;</b></div>
    <div class="ks">Owners on Reddit: ANC drops after a firmware update</div></div>
  <div class="card k" id="k3"><div class="kh">Other stores</div>
    <div class="row"><span>Store A</span><span>$124</span><b class="grn">Kernel verified</b></div>
    <div class="row"><span>Store B</span><span>$131</span><b class="grn">Kernel verified</b></div></div>
  <div class="card k" id="k4"><div class="kh">Alternatives</div>
    <div class="ks">Older model, same drivers &middot; $89</div></div>""",
    "verdict": """
  <div class="card verdict" id="vc"><div class="vl">Verdict</div><div class="vw">WAIT</div>
    <div class="conf"><div class="bar"><div class="fill" id="fill"></div></div><span>""" + odo("vp", "78") + """%</span></div>
    <div class="ks">The &ldquo;discount&rdquo; is fake and the price usually dips below $90 within a month.</div></div>
  <div class="wave" id="wave">""" + "".join(f'<i id="b{i}"></i>' for i in range(14)) + """</div>
  <div class="status">Second Look is speaking</div>""",
    "watch": """
  <div class="bubble user" id="q">Watch it under $85.</div>
  <div class="card k" id="w1"><div class="kh">&#128276; Watching <b class="acc">target $85</b></div>
    <div class="ks">I&rsquo;ll check the price every few hours.</div></div>
  <div class="card k email" id="w2"><div class="kh">&#9993; Price drop <b class="grn">now $84</b></div>
    <div class="ks">From the Second Look inbox &middot; AgentMail</div></div>
  <div class="saving" id="sv"><span>Saved so far</span><b>$""" + odo("wv", "45") + """</b></div>""",
}

PANEL_JS = {
    "ask": """
tl.from('#mic', {scale:0, duration:0.6, ease:'back.out(2)'}, 1.3);
const n = Math.max(1, Math.floor((D - 2) / 1.6));
tl.fromTo('#ring1', {scale:1, opacity:.6}, {scale:2.2, opacity:0, duration:1.6, ease:'power1.out', repeat:n - 1}, 1.6);
tl.fromTo('#ring2', {scale:1, opacity:.5}, {scale:2.2, opacity:0, duration:1.6, ease:'power1.out', repeat:n - 2}, 2.4);
tl.from('#status', {opacity:0, duration:0.5}, 1.8);
tl.from('#q', {opacity:0, y:20, duration:0.6, ease:'power3.out'}, D * 0.35);
tl.from('#a', {opacity:0, y:20, duration:0.6, ease:'power3.out'}, D * 0.6);
""",
    "cards": """
['#ch1','#ch2','#ch3'].forEach((s,i)=>tl.from(s, {opacity:0, x:30, duration:0.5, ease:'power3.out'}, 1.2 + i*0.4));
tl.to('.chip i', {rotation:360*Math.floor(D/1.2), duration:D - 4, ease:'none'}, 1.4);
['#k1','#k2','#k3','#k4'].forEach((s,i)=>tl.from(s, {opacity:0, y:40, duration:0.7, ease:'power3.out'}, D*0.12 + i*D*0.19));
""",
    "verdict": """
tl.from('#vc', {opacity:0, scale:0.9, duration:0.7, ease:'back.out(1.6)'}, 1.2);
tl.to('#fill', {width:'78%', duration:1.8, ease:'power2.out'}, 2.0);
""" + odo_js("vp", "78", 2.0, 1.6) + """
for (let i=0;i<14;i++){ tl.fromTo('#b'+i, {scaleY:0.2}, {scaleY:0.35+0.65*Math.abs(Math.sin(i*1.7)), duration:0.28+0.04*(i%5), yoyo:true,
  repeat:Math.floor((D-3)/(0.28+0.04*(i%5)))-1, ease:'sine.inOut'}, 2.4); }
""",
    "watch": """
tl.from('#q', {opacity:0, y:20, duration:0.6, ease:'power3.out'}, 1.2);
tl.from('#w1', {opacity:0, y:40, duration:0.7, ease:'power3.out'}, 2.6);
tl.from('#w2', {opacity:0, x:80, duration:0.7, ease:'power3.out'}, D*0.55);
tl.from('#sv', {opacity:0, y:20, duration:0.6}, D*0.62);
""" + odo_js("wv", "45", "D*0.65", 1.8),
}


def placeholder_html(dur: float, variant: str, filename: str, caption: str) -> str:
    f = FRAME
    css = BASE_CSS + f"""
.win{{position:absolute;left:{f['x']}px;top:{f['y']}px;width:{f['w']}px;height:{f['h']}px;border-radius:{f['r']}px;
     background:#10131A;border:1.5px solid var(--line);overflow:hidden;box-shadow:0 40px 120px rgba(0,0,0,.55),0 0 0 1px rgba(124,156,255,.06)}}
.bar{{height:56px;background:#151925;display:flex;align-items:center;padding:0 22px;gap:10px;border-bottom:1px solid var(--line)}}
.bar .d{{width:14px;height:14px;border-radius:50%;background:#3a4050}}
.url{{margin-left:22px;flex:1;height:34px;border-radius:10px;background:#0E1118;color:var(--mut);font-size:17px;display:flex;align-items:center;padding:0 16px}}
.ph{{margin-left:16px;font-size:15px;font-weight:700;letter-spacing:.1em;color:var(--wait);border:1.5px dashed rgba(255,181,71,.6);border-radius:8px;padding:6px 12px;text-transform:uppercase}}
.page{{position:absolute;left:0;top:56px;bottom:0;right:470px;padding:46px 56px;display:flex;gap:44px}}
.img{{width:420px;height:420px;border-radius:18px;background:linear-gradient(135deg,#1c2130,#141823);display:flex;align-items:center;justify-content:center}}
.img svg{{opacity:.5}}
.info{{flex:1;display:flex;flex-direction:column;gap:18px}}
.ln{{height:20px;border-radius:6px;background:#1b2030}}
.pp{{font-size:64px;font-weight:700;letter-spacing:-.03em;margin-top:10px}}
.pp s{{font-size:30px;color:var(--mut);font-weight:500;margin-left:16px}}
.pp em{{font-style:normal;font-size:24px;background:var(--skip);color:#0B0D12;border-radius:8px;padding:4px 10px;margin-left:12px;vertical-align:middle}}
.stars{{color:#F5C451;font-size:30px}}
.btn{{margin-top:16px;width:300px;height:58px;border-radius:14px;background:#2a3042}}
.what{{position:absolute;left:56px;bottom:40px;right:520px;font-size:24px;color:var(--mut);line-height:1.45}}
.what b{{color:var(--fg);font-weight:600}}
.panel{{position:absolute;right:0;top:56px;bottom:0;width:470px;background:#0D1017;border-left:1px solid var(--line);
       padding:26px 28px;display:flex;flex-direction:column;gap:16px}}
.ph-h{{display:flex;align-items:center;gap:12px;font-weight:700;font-size:24px;margin-bottom:6px}}
.ph-h .acc{{color:var(--acc)}}
.mic-wrap{{position:relative;height:250px;display:flex;align-items:center;justify-content:center}}
.mic{{position:relative;z-index:2;width:120px;height:120px;border-radius:50%;background:var(--acc);display:flex;align-items:center;justify-content:center}}
.ring{{position:absolute;width:120px;height:120px;border-radius:50%;border:4px solid var(--acc);opacity:0}}
.status{{text-align:center;color:var(--mut);font-size:20px}}
.bubble{{font-size:23px;line-height:1.4;padding:16px 20px;border-radius:18px;max-width:88%}}
.bubble.user{{align-self:flex-end;background:var(--acc);color:#0B0D12;font-weight:600;border-bottom-right-radius:6px}}
.bubble.agent{{align-self:flex-start;background:var(--card2);border-bottom-left-radius:6px}}
.chips{{display:flex;flex-wrap:wrap;gap:8px}}
.chip.c{{font-size:16px;font-weight:600;color:var(--fg);background:var(--card2);border:1px solid var(--line);border-radius:999px;padding:7px 12px;display:flex;align-items:center;gap:8px}}
.chip.c i{{display:inline-block;width:13px;height:13px;border-radius:50%;border:2.5px solid var(--acc);border-top-color:transparent}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 18px}}
.kh{{display:flex;justify-content:space-between;align-items:center;font-weight:600;font-size:20px}}
.kh b{{font-size:14px;letter-spacing:.06em;border-radius:6px;padding:4px 8px}}
.red{{background:rgba(255,107,107,.15);color:var(--skip)}} .amb{{background:rgba(255,181,71,.15);color:var(--wait)}}
.grn{{background:rgba(61,220,151,.13);color:var(--buy)}} .acc{{color:var(--acc)}}
.ks{{margin-top:8px;font-size:17px;color:var(--mut);line-height:1.4}}
.row{{display:flex;justify-content:space-between;align-items:center;font-size:18px;margin-top:9px}}
.row b{{font-size:12px;letter-spacing:.05em;border-radius:6px;padding:3px 7px}}
.verdict{{padding:26px 24px;margin-top:20px;border-color:rgba(255,181,71,.45)}}
.vl{{font-size:16px;letter-spacing:.14em;text-transform:uppercase;color:var(--mut)}}
.vw{{font-size:110px;font-weight:800;letter-spacing:-.02em;color:var(--wait);line-height:1.05}}
.conf{{display:flex;align-items:center;gap:14px;margin-top:10px;font-weight:700;font-size:22px;color:var(--wait)}}
.conf .bar{{flex:1;height:12px;border-radius:6px;background:#232838;padding:0;border:0}}
.conf .fill{{height:100%;width:0;border-radius:6px;background:var(--wait)}}
.wave{{display:flex;gap:7px;justify-content:center;align-items:center;height:110px;margin-top:20px}}
.wave i{{display:block;width:9px;height:90px;border-radius:5px;background:var(--acc);transform-origin:50% 50%;transform:scaleY(.2)}}
.email{{border-color:rgba(61,220,151,.45)}}
.saving{{margin-top:auto;display:flex;justify-content:space-between;align-items:center;background:rgba(61,220,151,.08);
        border:1px solid rgba(61,220,151,.35);border-radius:16px;padding:16px 20px;font-size:20px;color:var(--mut)}}
.saving b{{font-size:44px;color:var(--buy);letter-spacing:-.02em}}
"""
    body = f"""<div class="bgx"></div>
<div class="win" id="win">
  <div class="bar"><div class="d"></div><div class="d"></div><div class="d"></div>
    <div class="url">shop.example.com/product/wireless-noise-cancelling-headphones</div>
    <div class="ph">Placeholder &middot; recordings/{filename}</div></div>
  <div class="page">
    <div class="img"><svg viewBox="0 0 24 24" width="160" height="160"><path fill="#7C9CFF" d="M12 3a9 9 0 0 0-9 9v7a2 2 0 0 0 2 2h2v-7H5v-2a7 7 0 0 1 14 0v2h-2v7h2a2 2 0 0 0 2-2v-7a9 9 0 0 0-9-9z"/></svg></div>
    <div class="info"><div class="ln" style="width:92%"></div><div class="ln" style="width:70%"></div>
      <div class="stars">&#9733;&#9733;&#9733;&#9733;&#9734; <span style="color:#8A93A6;font-size:22px">4.6 &middot; 12,408 ratings</span></div>
      <div class="pp">$129<s>$199</s><em>35% off!</em></div>
      <div class="ln" style="width:84%"></div><div class="ln" style="width:76%"></div><div class="ln" style="width:58%"></div>
      <div class="btn"></div></div>
  </div>
  <div class="what" id="what"><b>Screen recording goes here.</b> {caption}</div>
  <div class="panel" id="panel">
    <div class="ph-h"><svg viewBox="0 0 260 180" width="46" height="32"><circle cx="100" cy="90" r="70" fill="none" stroke="#E8ECF4" stroke-opacity=".55" stroke-width="16"/><circle cx="160" cy="90" r="70" fill="none" stroke="#7C9CFF" stroke-width="16"/><circle cx="160" cy="90" r="22" fill="#7C9CFF"/></svg>Second <span class="acc">Look</span></div>
    {PANEL_CONTENT[variant]}
  </div>
</div>"""
    js = """
tl.from('#win', {opacity:0, y:30, scale:0.985, duration:0.7, ease:'power3.out'}, 0);
tl.from('#panel', {x:470, duration:0.8, ease:'power3.out'}, 0.5);
tl.from('#what', {opacity:0, duration:0.6}, 0.9);
""" + PANEL_JS[variant]
    return page(W, H, dur, body, css, js + DRIFT_JS)


# ------------------------------------------------------------------ s07 architecture (Motion Canvas)
ARCH_TSX = r'''
import {makeScene2D, Rect, Txt, Line, Circle, Node} from '@motion-canvas/2d';
import {all, sequence, waitFor, easeOutCubic, easeInOutCubic, createRef, Vector2, loop, linear} from '@motion-canvas/core';

const BG = '#0B0D12', ACC = '#7C9CFF', BUY = '#3DDC97', FG = '#E8ECF4', MUT = '#8A93A6', CARD = '#141823', LINE = '#2A3044';
const FONT = 'Avenir Next';
const P = __PARAMS__;

function box(x: number, y: number, w: number, h: number, title: string, sub: string, stroke: string, size = 40) {
  return (
    <Rect x={x} y={y} width={w} height={h} radius={22} fill={CARD} stroke={stroke} lineWidth={3} opacity={0} scale={0.85}
          shadowColor={'rgba(0,0,0,0.5)'} shadowBlur={40} layout direction={'column'} alignItems={'center'} justifyContent={'center'} gap={8}>
      <Txt text={title} fontFamily={FONT} fontWeight={700} fontSize={size} fill={FG} />
      <Txt text={sub} fontFamily={FONT} fontWeight={500} fontSize={24} fill={MUT} />
    </Rect>
  ) as Rect;
}

export default makeScene2D(function* (view) {
  view.add(<Rect width={1920} height={1080} fill={BG} />);
  const title = createRef<Txt>();
  view.add(<Txt ref={title} text={'UNDER THE HOOD'} fontFamily={FONT} fontWeight={700} fontSize={28} letterSpacing={6} fill={ACC} y={-450} opacity={0} />);

  const Y = -250;
  const a = box(-640, Y, 420, 170, 'Side panel', 'Chrome extension · mic + page', LINE);
  const b = box(0, Y, 440, 190, 'FastAPI backend', 'Python · Fly.io · live session', ACC, 44);
  const c = box(640, Y, 420, 170, 'Gemini 3.8 Live', 'hears you · sees the page', LINE);
  const ab = <Line points={[new Vector2(-430, Y), new Vector2(-220, Y)]} stroke={ACC} lineWidth={4} end={0} lineDash={[10, 8]} /> as Line;
  const bc = <Line points={[new Vector2(220, Y), new Vector2(430, Y)]} stroke={ACC} lineWidth={4} end={0} lineDash={[10, 8]} /> as Line;
  view.add(ab); view.add(bc); view.add(a); view.add(b); view.add(c);

  const lock = (
    <Rect y={Y + 135} height={46} radius={23} fill={'rgba(61,220,151,0.10)'} stroke={'rgba(61,220,151,0.55)'} lineWidth={2}
          layout padding={[0, 22]} alignItems={'center'} opacity={0}>
      <Txt text={'API keys stay on the server'} fontFamily={FONT} fontWeight={600} fontSize={22} fill={BUY} />
    </Rect>
  ) as Rect;
  view.add(lock);

  const tools = [
    ['Exa', 'owner reviews'], ['Kernel', 'cloud browser'], ['Neon', 'price memory'], ['AgentMail', 'price-drop email'], ['Jev · TypeSafe', 'the verdict'],
  ];
  const MID = -20;
  const TY = 170, xs = [-720, -360, 0, 360, 720];
  const tlines: Line[] = [], tboxes: Rect[] = [];
  tools.forEach(([t, s], i) => {
    const x = xs[i];
    const ln = <Line points={[new Vector2(0, Y + 172), new Vector2(0, MID), new Vector2(x, MID), new Vector2(x, TY - 70)]} radius={24}
                     stroke={LINE} lineWidth={3} end={0} /> as Line;
    const bx = box(x, TY, 320, 140, t, s, LINE, 34);
    view.add(ln); tlines.push(ln);
    view.add(bx); tboxes.push(bx);
  });
  a.moveToTop(); b.moveToTop(); c.moveToTop();

  // packets: the conversation never stops while tools run
  const pk1 = <Circle size={16} fill={ACC} x={-430} y={Y} opacity={0} /> as Circle;
  const pk2 = <Circle size={16} fill={ACC} x={220} y={Y} opacity={0} /> as Circle;
  view.add(pk1); view.add(pk2);
  const toolPk = xs.map(x => { const p = <Circle size={14} fill={BUY} x={0} y={Y + 172} opacity={0} /> as Circle; view.add(p); return p; });

  const T = P.timing || {};
  // first frame already shows the title and the side panel (no near-black opening frame after the dissolve)
  title().opacity(1); a.opacity(1); a.scale(1);
  yield* waitFor(0.3);
  yield* ab.end(1, 0.4, easeInOutCubic);
  yield* all(b.opacity(1, 0.5), b.scale(1, 0.5, easeOutCubic));
  yield* bc.end(1, 0.4, easeInOutCubic);
  yield* all(c.opacity(1, 0.5), c.scale(1, 0.5, easeOutCubic));

  // conversation packets loop in the background for the rest of the scene
  yield loop(40, () => all(
    pk1.opacity(1, 0).to(1, 0.55, linear).to(0, 0.1),
    pk1.x(-430, 0).to(-220, 0.65, linear),
    pk2.opacity(1, 0).to(1, 0.55, linear).to(0, 0.1),
    pk2.x(220, 0).to(430, 0.65, linear),
  ));
  yield* waitFor(T.lock ?? 1.2);
  yield* all(lock.opacity(1, 0.5), lock.y(Y + 145, 0.5, easeOutCubic));
  yield* waitFor(T.tools ?? 2.4);
  yield* sequence(0.22, ...tools.map((_, i) => all(
    tlines[i].end(1, 0.55, easeInOutCubic), tlines[i].stroke(ACC, 0.55),
    tboxes[i].opacity(1, 0.55), tboxes[i].scale(1, 0.55, easeOutCubic),
  )));
  // tool calls fan out while the packets keep flowing between the panel and Gemini
  yield* loop(T.fanouts ?? 3, () => sequence(0.15, ...toolPk.map((p, i) => all(
    p.opacity(1, 0.1).wait(0.7).to(0, 0.15),
    p.position(new Vector2(0, Y + 172), 0).to(new Vector2(0, MID), 0.2, linear).to(new Vector2(xs[i], MID), 0.3, linear).to(new Vector2(xs[i], TY - 70), 0.25, linear),
    tboxes[i].stroke(BUY, 0.2).wait(0.4).to(LINE, 0.4),
  ))));
  yield* waitFor(P.hold ?? 2);
});
'''


def arch_tsx(hold: float, lock_wait: float = 1.2, tools_wait: float = 2.4, fanouts: int = 3) -> str:
    import json
    return ARCH_TSX.replace("__PARAMS__", json.dumps({"hold": hold, "timing": {"lock": lock_wait, "tools": tools_wait, "fanouts": fanouts}}))
