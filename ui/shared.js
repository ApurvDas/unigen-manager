// Shared by index.html and widget.html: DOM helpers, the bridge to Python (api.py), and the anime.js motion components.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ================= bridge to Python (api.py) =================
// Inside the app, pywebview injects window.pywebview.api. Opened as index.html?mock (browser preview, UI tests),
// the page uses window.mockApi from mock-api.js. Inside the app it never falls back to mock data.
const MOCK = new URLSearchParams(location.search).has("mock");
const apiReady = new Promise(resolve => {
  if (MOCK) return resolve(window.mockApi);
  if (window.pywebview && window.pywebview.api) return resolve(window.pywebview.api);
  addEventListener("pywebviewready", () => resolve(window.pywebview.api), { once: true });
});
// call: resolves to data, or throws an Error whose message is safe to show
async function call(name, ...args) {
  const api = await apiReady;
  const r = await api[name](...args);
  if (!r || !r.ok) throw new Error(r && r.error ? r.error : "No answer from the app.");
  return r.data;
}

// ================= motion components (anime.js) =================
// Every click gets a response, sized to how often it happens:
// constant actions get near-invisible motion, rare ones get the most.
const ease = anime.cubicBezier(0.23, 1, 0.32, 1); // same curve as CSS --ease-out
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches; // reduced motion: fades only
const COLOR = k => ({ unigen: "var(--uni)", builtin: "var(--bi)" })[k] || "var(--muted)"; // an adapter's identity colour

// Timings (ms) of the switch area. The brutalist switch is crisp: it sinks onto its shadow and springs back, the
// indicator slides with no overshoot, and the progress bar only ever shows steps the app really performed.
const PRESS_MS = 90, RELEASE_MS = 220, PRESS_PX = 3; // the switch sinks PRESS_PX onto its shadow, then springs back
const SLIDE_MS = 220;                                // the indicator travelling to the chosen adapter
const ENTER_MS = 180, STAGGER_MS = 40;               // the bar grows in; its blocks follow one after another
const SWEEP_MS = 14000, SWEEP_TO = 0.7, SNAP_MS = 160; // the current block fills to 70% over a step's usual length, never full until it really ends
const FLASH_MS = 300, FOLD_MS = 400, LINGER_MS = 4000, FADE_MS = 200; // done: blocks flash green, fold to one line, linger, fade
const SHAKE_MS = 300, SHAKE_PX = 4;                  // the failed block
const PULSE_MS = 240, NOTE_MS = 2400;                // pressing a switch while a move runs
const TICK_MS = 1000;                                // the seconds counter
const SPRING = anime.spring({ stiffness: 520, damping: 22 });

// press: any clickable dips while the pointer is down, eases back on release. A switch sinks onto its hard shadow instead.
const PRESSABLE = ".btn, .adapter, nav button, .tabs button, .link, .icon-btn";
let pressed = null;
document.addEventListener("pointerdown", e => {
  const el = e.target.closest(`${PRESSABLE}, .seg button`);
  if (!el || el.disabled || reduce) return;
  pressed = el.closest(".seg") || el;
  if (pressed.matches(".seg")) anime.animate(pressed, { x: PRESS_PX, y: PRESS_PX, "--press": 1, duration: PRESS_MS, ease });
  else anime.animate(pressed, { scale: 0.97, duration: 120, ease });
});
["pointerup", "pointercancel"].forEach(t => document.addEventListener(t, () => {
  if (!pressed) return;
  if (pressed.matches(".seg")) anime.animate(pressed, { x: 0, y: 0, "--press": 0, duration: RELEASE_MS, ease: SPRING });
  else anime.animate(pressed, { scale: 1, duration: 200, ease });
  pressed = null;
}));

// slide: one highlight per group travels to the chosen item
function slide(ind, to, instant) {
  if (!to) return;
  const at = ind.dataset.axis === "x" ? { x: to.offsetLeft, width: to.offsetWidth } : { y: to.offsetTop, height: to.offsetHeight };
  if (instant || reduce) anime.set(ind, at);
  else anime.animate(ind, { ...at, duration: SLIDE_MS, ease });
}

// The Wi-Fi and Bluetooth switches (Dongle | Built-in) are built the same way in both windows.
const USE_LABEL = k => ({ unigen: "Dongle", builtin: "Built-in" })[k] || k;
const SWITCH_KEYS = [{ key: "unigen" }, { key: "builtin" }];
function buildSeg(seg, adapters) {
  seg.innerHTML = `<span class="ind" data-axis="x" aria-hidden="true"></span>` + adapters.map(a =>
    `<button role="radio" aria-checked="false" data-k="${esc(a.key)}">${esc(USE_LABEL(a.key))}</button>`).join("");
}
function markSeg(seg, key, instant) {
  seg.style.setProperty("--seg-c", COLOR(key)); // the indicator and the hard shadow take the chosen adapter's colour
  const bs = $$("button", seg);
  bs.forEach(b => b.setAttribute("aria-checked", b.dataset.k === key));
  slide($(".ind", seg), bs.find(b => b.dataset.k === key), instant);
}
const ADMIN_TIP = "Switching adapters needs administrator rights.";
// The dongle's state (api.app_info "dongle": connected, unplugged, not_responding; null when unknown): a status line, and the
// Dongle button of both switches is disabled until it is connected. Built-in stays usable.
const DONGLE_TEXT = { connected: "Dongle connected", unplugged: "Dongle not plugged in",
  not_responding: "Dongle not responding. Unplug it and plug it back in." };
const DONGLE_TIP = { unplugged: "Plug in the dongle.", not_responding: "Unplug the dongle and plug it back in." };
function renderDongle(el, state) {
  el.hidden = !state;
  el.dataset.state = state || "";
  setText($(".t", el), DONGLE_TEXT[state] || "");
}
// disabled without admin rights, and while a switch runs (Wi-Fi and Bluetooth share one lock)
function enableSeg(seg, admin, busy, dongle) {
  seg.title = admin ? "" : ADMIN_TIP;
  $$("button", seg).forEach(b => {
    const away = b.dataset.k === "unigen" && dongle in DONGLE_TIP;
    b.disabled = !admin || busy || away;
    b.title = away ? DONGLE_TIP[dongle] : "";
  });
}

// swap: a label changes with a short blur, so it reads as one control changing
function swap(btn, text) {
  const l = $(".label", btn);
  if (l.textContent === text) return;
  if (reduce) { l.textContent = text; return; }
  anime.animate(l, { opacity: 0.6, filter: "blur(2px)", duration: 100, ease, onComplete: () => {
    l.textContent = text;
    anime.animate(l, { opacity: 1, filter: "blur(0px)", duration: 140, ease });
  } });
}

// busy: the shared shape of every slow action. Disable, swap the label, show progress, await the work,
// then settle on `after` if it worked or the original label if it failed.
async function busy(btn, label, work, { prog, after } = {}) {
  const was = $(".label", btn).textContent;
  let ok = false;
  btn.disabled = true; swap(btn, label);
  if (prog) prog.hidden = false;
  try { const r = await work; ok = true; return r; }
  finally {
    btn.disabled = false; swap(btn, ok ? (after ?? was) : was);
    if (prog) prog.hidden = true;
  }
}

// arrive: a changed value settles in so the eye catches what changed
function arrive(el) {
  anime.animate(el, reduce ? { opacity: [0, 1], duration: 150, ease }
    : { opacity: [0, 1], y: [3, 0], duration: 200, ease });
}
function setText(el, text) {
  if (el.textContent === String(text)) return;
  el.textContent = text; arrive(el);
}
// setMsg: optional clearAfter (ms) lets the widget's confirmations fade away; 0 keeps the message
function setMsg(el, text, isErr, { clearAfter = 0 } = {}) {
  clearTimeout(el._t);
  el.textContent = text;
  el.classList.toggle("err", !!isErr);
  anime.waapi.animate(el, { opacity: [0, 1], duration: 150, ease });
  if (clearAfter) el._t = setTimeout(() => anime.waapi.animate(el, { opacity: 0, duration: 200, ease,
    onComplete: () => { el.textContent = ""; el.style.opacity = ""; } }), clearAfter);
}

// scramble: password reveal/hide (scrambleText writes innerHTML, so the text is escaped first)
function scramble(el, text) {
  if (reduce) { el.textContent = text; return arrive(el); }
  anime.animate(el, { innerHTML: anime.scrambleText({ text: esc(text) }), duration: 300 });
}

// pop: a status dot changes state (does nothing if it didn't change)
function pop(dot, on) {
  if (dot.classList.contains("on") === on) return;
  dot.classList.toggle("on", on);
  if (!reduce) anime.animate(dot, { scale: [1.8, 1], duration: 250, ease });
}

// layout transition on a list: mutate runs between record() and animate()
const layouts = new WeakMap();
function relayout(list, mutate, params) {
  let l = layouts.get(list);
  if (!l) layouts.set(list, l = anime.createLayout(list, { duration: 200, ease }));
  l.record(); mutate(); l.animate(params);
}
// removeEl: fades out while the rest slides into the gap
function removeEl(el, done) {
  const fin = () => { el.remove(); if (done) done(); };
  if (reduce) return anime.animate(el, { opacity: 0, duration: 150, ease, onComplete: fin });
  // the layout treats display:none as leaving, fades it out, then we drop it
  relayout(el.parentElement, () => el.style.display = "none", { onComplete: fin });
}
// addEl: appends a row that settles in
function addEl(list, html) {
  relayout(list, () => list.insertAdjacentHTML("beforeend", html),
    { enterFrom: reduce ? { opacity: 0 } : { opacity: 0, transform: "translateY(4px)" } });
}

// ================= switch progress =================
// The stepped bar under a switch. api.py pushes { kind, text, step, of, label, done, error } to onSwitchStep, one per
// step the app really performs; there is one block per step, the current step's name, "2/4 · 12 s", and never a made-up
// percentage. A block is empty, current (hatched, filling), done, skipped (nothing to do) or failed. A page builds the
// bar once (buildProgress), then hands every payload to renderStep.
const BAR_TITLE = { wifi: "Switching Wi-Fi", bt: "Moving Bluetooth" };
// the adapter a move is going to is named by the step that turns it on; that gives the bar its colour
const targetOf = text => {
  const m = /(?:turning on|moving bluetooth to|starting) the (.+?)(?: radio)?(?:…|\.|$)/i.exec(text || "");
  return !m ? null : /unigen|dongle/i.test(m[1]) ? "unigen" : /built-in|mediatek/i.test(m[1]) ? "builtin" : null;
};
function buildProgress(el, kind, { compact = false, onRetry } = {}) {
  if (el._st) stopBar(el._st);
  el._cfg = { kind, compact, onRetry }; el._st = null;
  el.className = compact ? "steps compact" : "steps";
  el.style.cssText = ""; el.dataset.bar = ""; el.dataset.kind = kind; el.hidden = true;
  el.innerHTML = `<div class="steps-body">
    <div class="steps-head"><span class="steps-title">${BAR_TITLE[kind]}</span><span class="steps-count num"></span></div>
    <div class="blocks" role="progressbar" aria-label="${BAR_TITLE[kind]}" aria-valuemin="0" aria-valuenow="0" aria-valuemax="0"></div>
    <div class="steps-label"></div>
    <div class="steps-fail" hidden><button class="btn small retry"><span class="label">Try again</span></button></div>
  </div><div class="steps-fold" hidden><span class="tick" aria-hidden="true">✓</span><span class="steps-fold-t"></span></div>`;
  $(".retry", el).addEventListener("click", () => el._cfg.onRetry && el._cfg.onRetry());
}
const blockEl = (el, n) => $$(".blk", el)[n - 1];
function stopBar(st) {
  clearInterval(st.timer);
  st.timers.forEach(clearTimeout);
  st.timers = []; st.timer = null;
  if (st.sweep) st.sweep.cancel();
  st.sweep = null;
}
function setBlock(el, st, n, state, snap) {
  const blk = blockEl(el, n);
  if (!blk) return;
  const fill = $("b", blk);
  blk.dataset.s = state;
  if (state === "current") {
    if (!reduce) st.sweep = anime.animate(fill, { scaleX: [0, SWEEP_TO], duration: SWEEP_MS, ease: "outQuad" }); // fills, but never to the end
    return;
  }
  if (n === st.cur && st.sweep) { st.sweep.cancel(); st.sweep = null; }
  if (state === "done" && snap && !reduce) anime.animate(fill, { scaleX: 1, duration: SNAP_MS, ease });
  else anime.set(fill, { scaleX: state === "empty" ? 0 : 1 });
}
function countText(el, st) {
  const secs = Math.floor((performance.now() - st.t0) / 1000);
  setText($(".steps-count", el), st.of ? `${Math.max(st.cur, 0)}/${st.of} · ${secs} s` : `${secs} s`);
}
function buildBlocks(el, st) {
  const box = $(".blocks", el);
  box.innerHTML = Array.from({ length: st.of }, () => `<i class="blk" data-s="empty"><b></b></i>`).join("");
  box.setAttribute("aria-valuemax", st.of);
  for (let i = 1; i < st.cur; i++) setBlock(el, st, i, "done");
  if (st.cur) setBlock(el, st, st.cur, "current");
  if (!reduce) anime.animate($$(".blk", el), { opacity: [0, 1], delay: anime.stagger(STAGGER_MS), duration: ENTER_MS, ease });
}
// the bar grows in (a compact one only fades: the widget window resizes to its content)
function enterBar(el) {
  el.hidden = false;
  if (reduce || el.classList.contains("compact")) return anime.animate(el, { opacity: [0, 1], duration: ENTER_MS, ease });
  const h = el.scrollHeight;
  el.style.overflow = "hidden";
  anime.animate(el, { height: [0, h], opacity: [0, 1], duration: ENTER_MS, ease, onComplete: () => { el.style.height = ""; el.style.overflow = ""; } });
}
// renderStep(el, payload, { to }): to is the adapter key a move started here is going to (others: read from the step text)
function renderStep(el, s, { to } = {}) {
  let st = el._st;
  if (st && st.over && s.done) return;  // already over (the page also reports a failed call)
  if (st && st.over) { buildProgress(el, el._cfg.kind, el._cfg); st = null; } // a new move while the last one lingers
  if (!st) {
    if (s.done) return;  // no step was ever shown: the page's own message says how it went
    st = el._st = { of: 0, cur: 0, t0: performance.now(), timers: [], sweep: null, timer: null, to: null, over: false };
    st.timer = setInterval(() => countText(el, st), TICK_MS);
    el.dataset.bar = "run";
    enterBar(el);
  }
  st.to = to || st.to || targetOf(s.text);
  el.style.setProperty("--accent", st.to ? COLOR(st.to) : "var(--ink)");
  if (s.of && s.of !== st.of) { st.of = s.of; buildBlocks(el, st); }
  if (s.done) return s.error ? failBar(el, st, s) : doneBar(el, st, s);
  const n = s.step || 0;
  if (n > st.cur) {  // the steps in between had nothing to do
    if (st.cur) setBlock(el, st, st.cur, "done", true);
    for (let i = st.cur + 1; i < n; i++) setBlock(el, st, i, "skipped");
    st.cur = n;
    setBlock(el, st, n, "current");
  }
  const bar = $(".blocks", el);
  bar.setAttribute("aria-valuenow", st.cur);
  bar.setAttribute("aria-valuetext", s.label || "");
  $(".steps-label", el).textContent = s.label || "";
  countText(el, st);
}
function failBar(el, st, s) {
  stopBar(st); st.over = true;
  el.dataset.bar = "fail";
  const n = s.step >= 1 && s.step <= st.of ? s.step : st.cur || 1;
  if (st.cur && st.cur !== n) setBlock(el, st, st.cur, "done");
  setBlock(el, st, n, "failed");
  const blk = blockEl(el, n);
  if (blk && !reduce) anime.animate(blk, { x: [0, -SHAKE_PX, SHAKE_PX, -SHAKE_PX, SHAKE_PX, -SHAKE_PX, SHAKE_PX, 0], duration: SHAKE_MS, ease: "linear" });
  setText($(".steps-count", el), st.of ? `${n}/${st.of} · failed` : "failed");
  $(".steps-label", el).textContent = s.label || "";
  const retry = $(".steps-fail", el);
  retry.hidden = false;
  arrive(retry);
}
// done: the last block fills, all blocks flash green, then the bar folds into one line and fades out after a while
function doneBar(el, st, s) {
  stopBar(st); st.over = true;
  el.dataset.bar = "done";
  const later = (fn, ms) => st.timers.push(setTimeout(fn, ms));
  for (let i = st.cur || 1; i <= st.of; i++) setBlock(el, st, i, blockEl(el, i)?.dataset.s === "skipped" ? "skipped" : "done", i === st.cur);
  const snap = reduce ? 0 : SNAP_MS, flash = reduce ? 0 : FLASH_MS;
  later(() => {
    if (!reduce) el.classList.add("ok");
    later(() => foldBar(el, st, s.text), flash);
  }, snap);
}
function foldBar(el, st, text) {
  const body = $(".steps-body", el), line = $(".steps-fold", el);
  $(".steps-fold-t", line).textContent = String(text || "").replace(/\.$/, "");
  line.hidden = false;
  if (reduce || el.classList.contains("compact")) {
    body.hidden = true;
    anime.animate(line, { opacity: [0, 1], duration: reduce ? FADE_MS : FOLD_MS, ease });
  } else {
    const was = body.offsetHeight, now = line.offsetHeight;
    el.style.overflow = "hidden";
    anime.animate(body, { height: [was, 0], opacity: [1, 0], duration: FOLD_MS, ease, onComplete: () => { body.hidden = true; } });
    anime.animate(line, { height: [0, now], opacity: [0, 1], duration: FOLD_MS, ease, onComplete: () => { el.style.overflow = ""; } });
  }
  st.timers.push(setTimeout(() => anime.animate(el, { opacity: 0, duration: FADE_MS, ease,
    onComplete: () => buildProgress(el, el._cfg.kind, el._cfg) }), FOLD_MS + LINGER_MS));
}
// a switch call that failed without the move saying so (no done step came): the bar fails at the step it was on
function failProgress(el, text) {
  const st = el._st;
  if (st && !st.over) renderStep(el, { kind: el._cfg.kind, text, done: true, error: true, step: st.cur, label: $(".steps-label", el).textContent });
}
// a page starting a new move, or leaving the bar behind: gone at once
function clearProgress(el) { if (el._cfg) buildProgress(el, el._cfg.kind, el._cfg); }
// pressing a switch while a move runs: the running bar pulses and says so for a moment, no error
function noteBar(el, text) {
  const st = el._st, t = $(".steps-title", el);
  if (!st || st.over) return;
  const was = el._cfg ? BAR_TITLE[el._cfg.kind] : "";
  t.textContent = text;
  clearTimeout(el._note);
  el._note = setTimeout(() => { t.textContent = was; }, NOTE_MS);
  anime.animate($(".blocks", el), reduce ? { opacity: [0.4, 1], duration: PULSE_MS, ease } : { scaleY: [1.8, 1], duration: PULSE_MS, ease });
}
