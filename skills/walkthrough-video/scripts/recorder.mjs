// Narration-paced screen recorder for web-app walkthroughs.
//
// A project's scenes.mjs imports createRecorder(), opens one browser context per role, and
// calls cue(id, actions, pre) once per narration line. Each cue lasts at least as long as its
// pre-voiced line (work/durations.json), so the voice never has to be squeezed to fit.
//
// Capture: CDP screencast frames always arrive at the viewport's CSS size, whatever the
// deviceScaleFactor, so for sharp zooms the viewport is SCALE x the layout size and the page is
// rendered with `body { zoom: SCALE }`. The layout the app sees is unchanged (1440x810 by default).
//
// Everything that happens is logged (moves, clicks, highlights, typing, page changes, camera cuts)
// so polish.py can direct the zoom afterwards.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { execFileSync } from 'node:child_process';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const HOME = process.env.VIDEO_STUDIO_HOME || path.join(os.homedir(), 'VideoStudio');   // workspace from setup.sh

function loadPlaywright(from) {
  const tries = [from, process.cwd()].filter(Boolean);
  for (const dir of tries) {
    try { return createRequire(path.join(dir, 'noop.js'))('playwright'); } catch {}
    const pnpm = path.join(dir, 'node_modules/.pnpm');
    if (fs.existsSync(pnpm)) {
      const hit = fs.readdirSync(pnpm).filter((d) => /^playwright@/.test(d)).sort().pop();
      if (hit) return createRequire(path.join(pnpm, hit, 'node_modules/playwright/noop.js'))('playwright');
    }
  }
  throw new Error('playwright not found: pass playwrightFrom (a repo that has it installed)');
}

function headlessShell() {
  const cache = process.platform === 'darwin'
    ? path.join(os.homedir(), 'Library/Caches/ms-playwright')
    : path.join(os.homedir(), '.cache/ms-playwright');
  if (!fs.existsSync(cache)) return undefined;
  const dirs = fs.readdirSync(cache).filter((d) => d.startsWith('chromium_headless_shell-')).sort();
  for (const d of dirs.reverse()) {
    const sub = fs.readdirSync(path.join(cache, d)).find((x) => x.startsWith('chrome-'));
    const exe = sub && path.join(cache, d, sub, 'chrome-headless-shell');
    if (exe && fs.existsSync(exe)) return exe;
  }
  return undefined;
}

// pointer, click ripple, highlight ring and role badge; mounted on <html>, outside React's
// <body> and outside the zoom, and only after load (mounting earlier breaks SSR hydration)
const overlay = (label, s, accent) => `(() => {
  const LABEL = ${JSON.stringify(label || '')}, S = ${s};
  const boot = () => {
    if (document.getElementById('__cur')) return;
    const css = document.createElement('style');
    css.textContent = \`
      #__cur{position:fixed;left:0;top:0;width:\${26*S}px;height:\${26*S}px;z-index:2147483647;pointer-events:none;
        transition:transform .7s cubic-bezier(.45,.05,.25,1);filter:drop-shadow(0 \${2*S}px \${3*S}px rgba(0,0,0,.35))}
      .__rip{position:fixed;width:\${34*S}px;height:\${34*S}px;margin:-\${17*S}px 0 0 -\${17*S}px;border-radius:50%;z-index:2147483646;
        pointer-events:none;border:\${3*S}px solid ${accent}d9;animation:__rip .55s ease-out forwards}
      @keyframes __rip{from{transform:scale(.3);opacity:1}to{transform:scale(1.6);opacity:0}}
      .__spot{position:fixed;z-index:2147483645;pointer-events:none;border-radius:\${8*S}px;
        box-shadow:0 0 0 \${3*S}px ${accent}e6,0 0 0 \${9*S}px ${accent}2e;animation:__spot 2.4s ease forwards}
      .__spot.live{animation:__spotin .3s ease forwards;transition:opacity .3s}
      @keyframes __spot{0%{opacity:0}12%{opacity:1}80%{opacity:1}100%{opacity:0}}
      @keyframes __spotin{from{opacity:0}to{opacity:1}}
      #__role{position:fixed;top:\${12*S}px;left:50%;transform:translateX(-50%);z-index:2147483644;pointer-events:none;
        font:600 \${13*S}px/1 -apple-system,"Segoe UI",sans-serif;letter-spacing:.02em;color:#fff;
        background:rgba(24,28,38,.86);padding:\${9*S}px \${14*S}px;border-radius:999px;transition:opacity .5s}
      #__role b{display:inline-block;width:\${8*S}px;height:\${8*S}px;border-radius:50%;background:${accent};margin-right:\${8*S}px;vertical-align:\${S}px}\`;
    document.documentElement.appendChild(css);
    const c = document.createElement('div'); c.id = '__cur';
    c.innerHTML = '<svg viewBox="0 0 26 26" width="' + 26*S + '" height="' + 26*S + '"><path d="M4 2 L4 21 L9 16.5 L12.5 24 L16 22.5 L12.6 15.2 L19.5 15.2 Z" fill="#fff" stroke="#1b1f2a" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    // the role badge shows for a few seconds when the camera cuts to this role, then fades: left on
    // screen it floats over the page content once the page scrolls
    let badge = null;
    if (LABEL) { badge = document.createElement('div'); badge.id = '__role'; badge.innerHTML = '<b></b>' + LABEL; document.documentElement.appendChild(badge); }
    const showBadge = () => {
      if (!badge) return;
      const left = +(sessionStorage.getItem('__badgeUntil') || 0) - Date.now();
      badge.style.opacity = left > 0 ? '1' : '0';
      if (left > 0) setTimeout(showBadge, left + 50);
    };
    showBadge();
    let p = JSON.parse(sessionStorage.getItem('__curpos') || JSON.stringify([innerWidth * .6, innerHeight * .64]));
    const place = (x, y, anim) => { c.style.transition = anim ? '' : 'none'; c.style.transform = 'translate(' + (x - 4*S) + 'px,' + (y - 2*S) + 'px)'; };
    place(p[0], p[1], false);
    window.__cur = {
      to(x, y) { p = [x, y]; sessionStorage.setItem('__curpos', JSON.stringify(p)); place(x, y, true); },
      click() { const d = document.createElement('div'); d.className = '__rip'; d.style.left = p[0] + 'px'; d.style.top = p[1] + 'px'; document.documentElement.appendChild(d); setTimeout(() => d.remove(), 700); },
      spot(r) { const d = document.createElement('div'); d.className = '__spot'; Object.assign(d.style, { left: (r.x - 8*S) + 'px', top: (r.y - 6*S) + 'px', width: (r.width + 16*S) + 'px', height: (r.height + 12*S) + 'px' }); document.documentElement.appendChild(d); setTimeout(() => d.remove(), 2500); },
      // a ring that follows its element every frame, so a late scroll or layout shift can't leave it
      // around empty space. b is Playwright's box (viewport px); the element's own rect only gives the motion.
      spotEl(el, b, life = 2400) {
        window.__cur.clear();                                    // one ring at a time
        const d = document.createElement('div'); d.className = '__spot live';
        const r0 = el.getBoundingClientRect(), k = r0.width ? b.width / r0.width : 1, t0 = performance.now();
        const fade = () => { d.style.opacity = '0'; setTimeout(() => d.remove(), 320); };
        const put = () => {
          if (!d.isConnected) return;
          const r = el.isConnected ? el.getBoundingClientRect() : null;
          if (!r || r.width === 0 || r.height === 0) return fade();   // the element went away: so does the ring
          let x = b.x + (r.left - r0.left) * k - 8*S, y = b.y + (r.top - r0.top) * k - 6*S;
          let w = b.width + 16*S, h = b.height + 12*S;
          const m = 4*S;                                         // keep the ring inside the screen
          const x1 = Math.min(innerWidth - m, x + w), y1 = Math.min(innerHeight - m, y + h);
          x = Math.max(m, x); y = Math.max(m, y); w = x1 - x; h = y1 - y;
          if (w < 8*S || h < 8*S) { d.style.opacity = '0'; } else { d.style.opacity = ''; }
          Object.assign(d.style, { left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px' });
          if (performance.now() - t0 < life) requestAnimationFrame(put); else fade();
        };
        document.documentElement.appendChild(d); put();
      },
      clear() { document.querySelectorAll('.__spot').forEach((d) => { d.style.opacity = '0'; setTimeout(() => d.remove(), 320); }); },
      badge(ms = 4000) { sessionStorage.setItem('__badgeUntil', String(Date.now() + ms)); showBadge(); },
    };
  };
  const start = () => { setTimeout(boot, 400); setInterval(() => { if (!document.getElementById('__cur')) boot(); }, 500); };
  if (document.readyState === 'complete') start(); else window.addEventListener('load', start);
})();`;

const zoomScript = (s) => `(() => { const add = () => { const st = document.createElement('style'); st.textContent = 'body{zoom:${s}}'; document.documentElement.appendChild(st); }; if (document.documentElement) add(); else document.addEventListener('readystatechange', add, { once: true }); })();`;

const cardHtml = ({ brand, accent, title, sub, foot, s }) => `<!doctype html><html><head><style>
  html,body{margin:0;height:100%} body{zoom:${s}}
  body{display:grid;place-items:center;background:#f7f6f7;font-family:-apple-system,"Segoe UI",sans-serif;color:#1b1f2a}
  .wrap{display:grid;gap:22px;justify-items:center;text-align:center}
  .brand{font-weight:700;letter-spacing:.14em;font-size:20px} .brand i{display:inline-block;width:12px;height:12px;border-radius:50%;background:${accent};margin-right:12px}
  h1{margin:0;font-size:64px;font-weight:700;letter-spacing:-.02em} p{margin:0;font-size:22px;color:#5a5f6c}
  .rule{width:72px;height:4px;border-radius:2px;background:${accent}}
  .foot{position:fixed;bottom:36px;left:0;right:0;text-align:center;font-size:14px;color:#8a8f9c;letter-spacing:.04em}
</style></head><body><div class="wrap"><div class="brand"><i></i>${brand}</div><h1>${title}</h1><div class="rule"></div><p>${sub}</p></div><div class="foot">${foot || ''}</div></body></html>`;

export async function createRecorder({
  project,                    // the project folder (~/VideoStudio/projects/<name>)
  baseURL,
  playwrightFrom,             // a folder whose node_modules has playwright (e.g. the app repo)
  layout = { width: 1440, height: 810 },
  scale = 2,
  brand = '', accent = '#c8104a',
} = {}) {
  const WORK = path.join(project, 'work');
  const LINES = JSON.parse(fs.readFileSync(path.join(WORK, 'lines.json'), 'utf8'));
  const DUR = JSON.parse(fs.readFileSync(path.join(WORK, 'durations.json'), 'utf8'));
  for (const id of Object.keys(LINES)) if (!(id in DUR)) throw new Error(`line ${id} has no voice yet: run tts_prep.py`);
  const FRAMES = path.join(WORK, 'frames');
  fs.rmSync(FRAMES, { recursive: true, force: true }); fs.mkdirSync(FRAMES, { recursive: true });
  const VW = layout.width * scale, VH = layout.height * scale;

  const { chromium } = loadPlaywright(playwrightFrom);
  const browser = await chromium.launch({ executablePath: headlessShell() });

  let T0 = 0;
  const now = () => (T0 ? (Date.now() - T0) / 1000 : 0);
  const frames = [], cues = [], events = [], problems = [], speedups = [];
  const ev = (k, o = {}) => { if (T0) events.push({ t: +now().toFixed(3), k, ...o }); };
  const note = (msg) => { problems.push(msg); console.log('PROBLEM', msg); };

  // ---- capture ----
  let onAir = null, lastKept = -1;
  const cdps = new Map();
  function keep(data) {
    if (!T0) return;
    const t = now();
    if (t - lastKept < 1 / 32) return;
    lastKept = t;
    const f = `f${String(frames.length).padStart(6, '0')}.jpg`;
    fs.writeFileSync(path.join(FRAMES, f), Buffer.from(data, 'base64'));
    frames.push({ f, t });
  }
  async function cdpFor(page) {
    if (cdps.has(page)) return cdps.get(page);
    const s = await page.context().newCDPSession(page);
    s.on('Page.screencastFrame', ({ data, sessionId }) => { if (onAir === s) keep(data); s.send('Page.screencastFrameAck', { sessionId }).catch(() => {}); });
    cdps.set(page, s);
    return s;
  }
  /** Put a page on camera (the first call starts the clock). */
  async function camera(page) {
    const s = await cdpFor(page);
    if (onAir === s) return;
    if (!T0) T0 = Date.now();
    if (onAir) await onAir.send('Page.stopScreencast').catch(() => {});
    ev('cut', { card: page === cardPage, first: !onAir });
    onAir = s;
    if (page !== cardPage) await page.evaluate(() => window.__cur && window.__cur.badge()).catch(() => {});
    keep((await s.send('Page.captureScreenshot', { format: 'jpeg', quality: 90 })).data);
    await s.send('Page.startScreencast', { format: 'jpeg', quality: 90, maxWidth: VW, maxHeight: VH, everyNthFrame: 1 });
  }

  // ---- contexts ----
  /** A signed-in browser for one role. signIn(page) runs before recording; label shows on screen. */
  async function role({ label, signIn, start }) {
    const ctx = await browser.newContext({ viewport: { width: VW, height: VH }, deviceScaleFactor: 1 });
    await ctx.addInitScript(zoomScript(scale));
    await ctx.addInitScript(overlay(label, scale, accent));
    const page = await ctx.newPage();
    if (signIn) await signIn(page, { baseURL });
    if (start) { await page.goto(new URL(start, baseURL).href, { waitUntil: 'networkidle' }); await sleep(1200); }
    return page;
  }
  let cardPage = null;
  /** Show a title card (opens its own page the first time). */
  async function card(title, sub = '', foot = '') {
    if (!cardPage) { const ctx = await browser.newContext({ viewport: { width: VW, height: VH }, deviceScaleFactor: 1 }); cardPage = await ctx.newPage(); }
    await cardPage.setContent(cardHtml({ brand, accent, title, sub, foot, s: scale }));
    await sleep(300);
    return cardPage;
  }

  // ---- pacing ----
  /** One narration line. `pre` runs first, silently (page loads); `fn` runs while the line plays. */
  async function cue(id, fn, pre) {
    if (!LINES[id]) throw new Error('no narration line ' + id);
    if (pre) {
      const p0 = now();
      try { await pre(); } catch (e) { note(`${id} (before): ${e.message.split('\n')[0]}`); }
      await sleep(500);
      const p1 = now();
      ev('pre', { t0: +p0.toFixed(3), t1: +p1.toFixed(3) });
      if (p1 - p0 > 1.6) speedups.push([+(p0 + 0.3).toFixed(2), +(p1 - 0.3).toFixed(2), 2]);
    }
    const start = now();
    cues.push({ id, t: start });
    line = { t0: Date.now(), end: Date.now() + DUR[id] * 1000 };
    try { if (fn) await fn(); } catch (e) { note(`${id}: ${e.message.split('\n')[0]}`); }
    const voiceEnd = start + DUR[id] + 0.6;
    const done = now();
    if (done > voiceEnd + 1.5) speedups.push([+(voiceEnd + 0.3).toFixed(2), +(done - 0.2).toFixed(2), 2]);
    const rem = voiceEnd - now();
    if (rem > 0) await sleep(rem * 1000);
    line = null;
    for (const pg of cdps.keys()) await pg.evaluate(() => window.__cur && window.__cur.clear()).catch(() => {});
  }
  let line = null;      // the narration line now playing: { t0, end } (ms)
  /** Wait until this fraction of the current line has been spoken, so an action lands on the words
   *  that name it ("…and we accept them" -> await at(0.7); await click(...)). */
  async function at(frac) {
    if (!line) return;
    const wait = line.t0 + frac * (line.end - line.t0) - Date.now();
    if (wait > 0) await sleep(wait);
  }

  // ---- hands (every one logs what it did, for the zoom) ----
  const margin = 70 * scale;
  /** The element's box once it has stopped moving (smooth scrolls, layout shifts, loading content).
   *  A fixed sleep isn't enough: a long smooth scroll is still moving after it, and anything measured
   *  mid-scroll (the camera target, the highlight ring) lands on empty space. */
  async function stable(loc, timeout = 3000) {
    let prev = await loc.boundingBox(), same = 0;
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      await sleep(90);
      const b = await loc.boundingBox();
      if (b && prev && Math.abs(b.x - prev.x) < 0.5 && Math.abs(b.y - prev.y) < 0.5 && Math.abs(b.height - prev.height) < 0.5) {
        if (++same >= 3) return b;
      } else same = 0;
      prev = b;
    }
    return prev;
  }
  /** Wait until the page itself has stopped scrolling. */
  async function scrolled(page, timeout = 3000) {
    let prev = null, same = 0;
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      const y = await page.evaluate(() => window.scrollY);
      if (prev !== null && Math.abs(y - prev) < 0.5) { if (++same >= 3) break; } else same = 0;
      prev = y;
      await sleep(90);
    }
    await sleep(150);
  }
  async function center(loc) {
    await loc.waitFor({ state: 'visible', timeout: 8000 });
    let b = await stable(loc);
    if (!b || b.y < margin || b.y + b.height > VH - margin) {
      await loc.evaluate((el) => el.scrollIntoView({ behavior: 'smooth', block: 'center' }));
      await sleep(300);
      b = await stable(loc);
    }
    return { x: b.x + Math.min(b.width / 2, 60 * scale), y: b.y + b.height / 2, b };
  }
  /** Move the pointer to an element. */
  async function point(page, loc, pause = 300) {
    const g = await center(loc);
    ev('move', { x: g.x, y: g.y, box: g.b });
    await page.evaluate(([x, y]) => window.__cur.to(x, y), [g.x, g.y]);
    await sleep(750 + pause);
    return g;
  }
  /** Draw a highlight ring around an element (the camera may zoom to it). */
  async function spot(page, loc) {
    await quiet(page);
    const { b } = await center(loc);
    ev('spot', { box: b });
    // the ring stays until the line that talks about it has been spoken (at least 2.4 s)
    const life = Math.max(2400, line ? line.end - Date.now() + 300 : 2400);
    await loc.evaluate((el, [r, ms]) => window.__cur.spotEl(el, r, ms), [b, life]);
    await sleep(400);
  }
  async function click(page, loc) {
    const g = await point(page, loc, 120);
    ev('click', { x: g.x, y: g.y, box: g.b });
    await page.evaluate(() => window.__cur.click());
    await loc.click();
    await sleep(500);
  }
  /** Wait until the app's saves have finished; acting before that races its own requests. */
  async function settle(page) { await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {}); await quiet(page); await sleep(300); }
  /** Wait until the page stops changing: no DOM changes for `ms` and no loading placeholders
   *  (aria-busy, skeletons, progress bars). Network-idle alone still leaves skeletons on camera. */
  async function quiet(page, ms = 500, timeout = 6000) {
    await page.evaluate(([ms, timeout]) => new Promise((res) => {
      const t0 = performance.now(); let last = t0;
      const busy = () => document.querySelector('[aria-busy="true"], [class*="skeleton" i], [role="progressbar"]');
      const mo = new MutationObserver(() => { last = performance.now(); });
      mo.observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
      const tick = () => {
        const n = performance.now();
        if ((n - last > ms && !busy()) || n - t0 > timeout) { mo.disconnect(); res(); } else setTimeout(tick, 100);
      };
      tick();
    }), [ms, timeout]).catch(() => {});
  }
  async function type(page, loc, text, { clear = false, delay = 65 } = {}) {
    await click(page, loc);
    if (clear) { await page.keyboard.press('ControlOrMeta+A'); await page.keyboard.press('Backspace'); }
    const tb = await loc.boundingBox();
    ev('type', { box: tb });
    await loc.pressSequentially(text, { delay });
    ev('typeEnd', { box: tb });
    await sleep(250);
  }
  /** Leave a field the way a person does (apps that save on blur save here). */
  async function tabOut(page) { await page.keyboard.press('Tab'); await sleep(900); await settle(page); }
  /** Open a dropdown (a button by accessible name) and choose an option; retries once if the app reports a failed save. */
  async function pick(page, buttonName, option, { failed = /could not be saved/i } = {}, retry = true) {
    await settle(page);
    await click(page, page.getByRole('button', { name: buttonName }).first());
    const o = page.getByRole('option', { name: option, exact: true }).first();
    await o.scrollIntoViewIfNeeded();
    await sleep(300);
    await click(page, o);
    await settle(page);
    await sleep(600);
    if (retry && failed && (await page.getByText(failed).count())) { note('re-picked ' + option); await pick(page, buttonName, option, { failed }, false); }
  }
  async function scrollTo(page, y) { ev('scroll'); await page.evaluate((y) => window.scrollTo({ top: y, behavior: 'smooth' }), y * scale); await sleep(300); await scrolled(page); }
  /** Mark a page change, so the camera stays wide while the next page loads. */
  const nav = () => ev('nav');
  async function navClick(page, loc) { nav(); await click(page, loc); await settle(page); await sleep(600); }
  async function goto(page, url) { nav(); await page.goto(new URL(url, baseURL).href, { waitUntil: 'networkidle' }); await sleep(1000); }

  // ---- finish ----
  async function finish({ tail = 2.5 } = {}) {
    await sleep(tail * 1000);
    const END = now();
    await browser.close();
    fs.writeFileSync(path.join(WORK, 'cues.json'), JSON.stringify({ cues, problems, speedups, events, end: END, scale, layout }, null, 1));
    let list = '';
    for (let i = 0; i < frames.length; i++) {
      const next = i + 1 < frames.length ? frames[i + 1].t : END;
      list += `file '${path.join(FRAMES, frames[i].f)}'\nduration ${Math.max(0.001, next - frames[i].t).toFixed(4)}\n`;
    }
    list += `file '${path.join(FRAMES, frames[frames.length - 1].f)}'\n`;
    fs.writeFileSync(path.join(WORK, 'frames.txt'), list);
    execFileSync(path.join(HOME, 'bin/ffmpeg'), ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0',
      '-i', path.join(WORK, 'frames.txt'), '-vf', 'fps=30,scale=1920:1080:flags=lanczos,format=yuv420p',
      '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-movflags', '+faststart', path.join(WORK, 'recording.mp4')]);
    const pj = path.join(project, 'project.json');
    const cfg = JSON.parse(fs.readFileSync(pj, 'utf8'));
    cfg.speedups = speedups;
    fs.writeFileSync(pj, JSON.stringify(cfg, null, 1));
    fs.writeFileSync(path.join(project, 'script.tsv'), cues.map((c) => `${c.t.toFixed(2)}\t${LINES[c.id]}`).join('\n') + '\n');
    const missing = Object.keys(LINES).filter((id) => !cues.some((c) => c.id === id));
    console.log(`frames ${frames.length}, length ${END.toFixed(1)}s, ${cues.length} cues, ${speedups.length} speed-ups, problems ${problems.length}`);
    for (const p of problems) console.log('  ' + p);
    if (missing.length) console.log('  lines never cued: ' + missing.join(', '));
    return { problems, missing };
  }

  return { role, card, camera, cue, at, point, spot, click, type, tabOut, settle, quiet, pick, scrollTo, nav, navClick, goto, finish, sleep, note, scale };
}
