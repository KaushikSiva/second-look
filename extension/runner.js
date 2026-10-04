/* Second Look — a tiny endless runner that plays while the research is running.
   Three rails recede to a vanishing point; the runner dodges fake "-35%" discounts and picks up brass price tags.
   Auto-pilots by default; tap the left/right half (or ←/→) to switch rails yourself. */
(() => {
  const RAILS = [-1, 0, 1];
  let canvas, ctx, wrap, raf = 0, running = false, last = 0, t = 0;
  let lane = 0, laneX = 0, jump = 0, items = [], spawnIn = 0, deals = 0, dodged = 0, manualUntil = 0, hitFlash = 0;

  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

  function build() {
    wrap = document.createElement('section');
    wrap.className = 'runner';
    wrap.innerHTML = `<canvas aria-label="Mini game: dodge fake discounts while Second Look researches"></canvas>
      <div class="runner-hud"><span>Dodging fake discounts while I dig</span><span class="runner-score num"></span></div>`;
    canvas = wrap.querySelector('canvas');
    ctx = canvas.getContext('2d');
    canvas.addEventListener('pointerdown', (e) => {
      const r = canvas.getBoundingClientRect();
      steer(e.clientX - r.left < r.width / 2 ? -1 : 1);
    });
    document.addEventListener('keydown', (e) => {
      if (!running || document.activeElement?.tagName === 'INPUT') return;
      if (e.key === 'ArrowLeft') steer(-1);
      if (e.key === 'ArrowRight') steer(1);
      if (e.key === 'ArrowUp' || e.key === ' ') jump = jump || 1;
    });
    const anchor = document.getElementById('activity');
    anchor.parentNode.insertBefore(wrap, anchor);
  }

  function steer(d) { lane = Math.max(-1, Math.min(1, lane + d)); manualUntil = t + 2.5; }

  function size() {
    const dpr = window.devicePixelRatio || 1;
    const w = wrap.clientWidth, h = 150;
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { w, h };
  }

  // depth z: 0 = horizon, 1 = at the runner's feet
  const proj = (w, h, rail, z) => {
    const horizonY = 22, footY = h - 18;
    const y = horizonY + (footY - horizonY) * z;
    const spread = (w * 0.30) * (0.12 + 0.88 * z);
    return { x: w / 2 + rail * spread, y, s: 0.25 + 0.75 * z };
  };

  function spawn() {
    const rail = RAILS[Math.floor(Math.random() * 3)];
    const kind = Math.random() < 0.55 ? 'fake' : 'deal';
    items.push({ rail, z: 0, kind, done: false });
    spawnIn = 0.55 + Math.random() * 0.5;
  }

  function autopilot() {
    if (t < manualUntil) return;
    // look at the nearest threat or deal in the next stretch and pick a rail
    const ahead = items.filter((i) => !i.done && i.z > 0.45 && i.z < 0.95);
    const threat = (r) => ahead.some((i) => i.kind === 'fake' && i.rail === r);
    const deal = ahead.find((i) => i.kind === 'deal' && !threat(i.rail));
    if (threat(lane)) {
      const opts = [lane - 1, lane + 1].filter((r) => r >= -1 && r <= 1 && !threat(r));
      if (opts.length) lane = opts[0]; else jump = jump || 1;
    } else if (deal && Math.abs(deal.rail - lane) === 1) {
      lane = deal.rail;
    }
  }

  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000 || 0.016);
    last = now; t += dt;
    const { w, h } = size();
    const speed = 0.62;
    spawnIn -= dt; if (spawnIn <= 0) spawn();
    autopilot();
    laneX += (lane - laneX) * Math.min(1, dt * 12);
    if (jump) { jump += dt * 2.6; if (jump >= 2) jump = 0; }
    const lift = jump ? Math.sin((jump - 1) * Math.PI) * 26 : 0;

    for (const it of items) {
      it.z += dt * speed * (0.5 + it.z);
      if (!it.done && it.z > 0.9 && it.z < 1.02) {
        const same = Math.abs(it.rail - laneX) < 0.45;
        if (same && it.kind === 'deal') { it.done = true; deals++; }
        if (same && it.kind === 'fake' && lift < 12) { it.done = true; hitFlash = 1; }
        if (!same && it.kind === 'fake' && it.z > 1) { it.done = true; dodged++; }
      }
    }
    items = items.filter((i) => i.z < 1.15 && !(i.done && i.kind === 'deal'));

    // --- draw ---
    const ink = css('--text'), rule = css('--rule') || css('--border'), smoke = css('--text-3');
    const brass = css('--brass') || '#C8A25E', red = css('--red');
    ctx.clearRect(0, 0, w, h);
    // sleepers
    ctx.strokeStyle = rule; ctx.lineWidth = 1;
    for (let k = 0; k < 14; k++) {
      const z = ((k / 14) + (t * speed * 0.9) % (1 / 14)) % 1;
      const zz = z * z;
      const a = proj(w, h, -1.45, zz), b = proj(w, h, 1.45, zz);
      ctx.globalAlpha = 0.2 + zz * 0.7;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    // rails
    for (const r of [-1.5, -0.5, 0.5, 1.5]) {
      const a = proj(w, h, r, 0), b = proj(w, h, r, 1.1);
      ctx.strokeStyle = smoke; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    // items, far to near
    for (const it of items.slice().sort((a, b) => a.z - b.z)) {
      const p = proj(w, h, it.rail, Math.min(it.z, 1.1));
      ctx.globalAlpha = Math.min(1, it.z * 3);
      if (it.kind === 'fake') {
        const bw = 46 * p.s, bh = 22 * p.s;
        ctx.strokeStyle = red; ctx.lineWidth = 1.2;
        ctx.strokeRect(p.x - bw / 2, p.y - bh - 2, bw, bh);
        ctx.fillStyle = red; ctx.font = `500 ${Math.max(7, 12 * p.s)}px "Plex Mono", monospace`;
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText('−35%', p.x, p.y - bh / 2 - 2);
      } else {
        const s = 11 * p.s;
        ctx.fillStyle = brass;
        ctx.beginPath();
        ctx.moveTo(p.x - s, p.y - 3 - s * 1.2); ctx.lineTo(p.x + s * 0.4, p.y - 3 - s * 1.2);
        ctx.lineTo(p.x + s, p.y - 3 - s * 0.6); ctx.lineTo(p.x + s * 0.4, p.y - 3); ctx.lineTo(p.x - s, p.y - 3); ctx.closePath();
        ctx.fill();
        ctx.fillStyle = css('--bg'); ctx.beginPath(); ctx.arc(p.x + s * 0.35, p.y - 3 - s * 0.6, s * 0.16, 0, 7); ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
    // runner: a chalk figure with a stride cycle
    const me = proj(w, h, laneX, 1);
    const cy = me.y - 4 - lift, ph = t * 14;
    ctx.strokeStyle = hitFlash > 0 ? red : ink; ctx.lineWidth = 2.2; ctx.lineCap = 'round';
    const leg = (o) => { ctx.beginPath(); ctx.moveTo(me.x, cy - 18); ctx.lineTo(me.x + Math.sin(ph + o) * 7, cy - 9); ctx.lineTo(me.x + Math.sin(ph + o) * 9 - 2, cy); ctx.stroke(); };
    const arm = (o) => { ctx.beginPath(); ctx.moveTo(me.x, cy - 30); ctx.lineTo(me.x + Math.sin(ph + o) * 8, cy - 22); ctx.stroke(); };
    leg(0); leg(Math.PI); arm(Math.PI); arm(0);
    ctx.beginPath(); ctx.moveTo(me.x, cy - 18); ctx.lineTo(me.x + 1.5, cy - 33); ctx.stroke();
    ctx.fillStyle = ctx.strokeStyle; ctx.beginPath(); ctx.arc(me.x + 2, cy - 38, 4.2, 0, 7); ctx.fill();
    // shadow
    ctx.fillStyle = rule; ctx.globalAlpha = 0.8;
    ctx.beginPath(); ctx.ellipse(me.x, me.y - 1, 10 - lift / 5, 2.2, 0, 0, 7); ctx.fill(); ctx.globalAlpha = 1;
    hitFlash = Math.max(0, hitFlash - dt * 3);

    wrap.querySelector('.runner-score').textContent = `${deals} deals · ${dodged} dodged`;
    if (running) raf = requestAnimationFrame(frame);
  }

  window.SLRunner = {
    show() {
      if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      if (!wrap) build();
      if (running) return;
      running = true; items = []; spawnIn = 0.3; lane = 0; laneX = 0; t = 0;
      wrap.classList.remove('out'); wrap.hidden = false;
      last = performance.now(); raf = requestAnimationFrame(frame);
    },
    hide() {
      if (!wrap || !running) return;
      wrap.classList.add('out');
      setTimeout(() => { running = false; cancelAnimationFrame(raf); wrap.hidden = true; }, 450);
    },
  };
})();
