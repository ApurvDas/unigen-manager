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

// press: any clickable dips while the pointer is down, eases back on release
const PRESSABLE = ".btn, .adapter, nav button, .tabs button, .link, .seg button, .icon-btn";
let pressed = null;
document.addEventListener("pointerdown", e => {
  const el = e.target.closest(PRESSABLE);
  if (!el || el.disabled || reduce) return;
  pressed = el;
  anime.animate(el, { scale: 0.97, duration: 120, ease });
});
["pointerup", "pointercancel"].forEach(t => document.addEventListener(t, () => {
  if (pressed) anime.animate(pressed, { scale: 1, duration: 200, ease });
  pressed = null;
}));

// slide: one highlight per group travels to the chosen item
function slide(ind, to, instant) {
  if (!to) return;
  const at = ind.dataset.axis === "x" ? { x: to.offsetLeft, width: to.offsetWidth } : { y: to.offsetTop, height: to.offsetHeight };
  if (instant || reduce) anime.set(ind, at);
  else anime.animate(ind, { ...at, duration: 200, ease });
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
