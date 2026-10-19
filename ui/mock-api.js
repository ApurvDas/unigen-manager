// Stand-in for api.py when the page is opened as index.html?mock (browser preview and UI tests).
// Same method names and data shapes as the Python Api; tests/test_api.py checks that the names match.
// Test hooks (set before the page loads): MOCK_FAST (no delays), MOCK_FAIL = { method: "message" },
// MOCK_UNPLUG = "unigen" | "builtin", MOCK_ADMIN = false, MOCK_HOSTILE (adds a network, saved profile and paired device named like an HTML tag),
// MOCK_SEARCH_HOLD (the Bluetooth search never finishes), MOCK_PAIR_TWIN (pairing races a paired-list refresh), MOCK_BT_OFF (Bluetooth starts off),
// MOCK_BOTH_ON (neither adapter is switched off, like before the first switch), MOCK_OTHER_RADIO (two paired devices are paired
// only with the other radio: Re-pair instead of Connect), MOCK_BT_FAIL = "message" (the background Bluetooth move fails).
// window.mockApi._setUsing(key, kind) changes the adapter Wi-Fi ("wifi") or Bluetooth ("bt") uses, both without a kind;
// mockApi._setConnected(id, on) connects a paired device behind the app's back (as Windows Settings would);
// mockApi._setHere(id, on) moves a paired device to / from the other radio behind the app's back.
// Mock nearby devices carry ceremony null | "confirm" | "display" | "provide"; the PIN shown is 482913 and the right provide PIN is 0000.
window.mockApi = (() => {
  const wait = ms => new Promise(r => setTimeout(r, window.MOCK_FAST ? 0 : ms));
  const api = {};
  function def(name, ms, fn) {
    api[name] = async (...args) => {
      if (window.MOCK_LOG) window.MOCK_LOG.push(name);
      await wait(ms);
      const fail = (window.MOCK_FAIL || {})[name];
      if (fail) return { ok: false, error: fail };
      try { return { ok: true, data: (await fn(...args)) ?? null }; }
      catch (e) { return { ok: false, error: e.message }; }
    };
  }

  const NAMES = { unigen: "Unigen dongle", builtin: "Built-in MediaTek" };
  const ADAPTERS = [
    { key: "unigen", name: NAMES.unigen, bt: "5.4", state: "connected", ssid: "HOME-5G", signal: 97, rate: 433, channel: 36, band: 5 },
    { key: "builtin", name: NAMES.builtin, bt: "5.2", state: "connected", ssid: "HOME-5G", signal: 80, rate: 866, channel: 36, band: 5 },
  ];
  const NETS = [
    { ssid: "HOME-5G", auth: "WPA2-Personal", aps: [{ b: 5, ch: 36, s: 96 }] },
    { ssid: "Maple House", auth: "WPA2-Personal", aps: [{ b: 2.4, ch: 6, s: 92 }, { b: 2.4, ch: 1, s: 38 }] },
    { ssid: "AirFiber-Maple House", auth: "WPA2-Personal", aps: [{ b: 2.4, ch: 11, s: 48 }, { b: 5, ch: 157, s: 18 }] },
    { ssid: "AirFiber-Cedar12", auth: "WPA2-Personal", aps: [{ b: 2.4, ch: 1, s: 46 }, { b: 5, ch: 157, s: 14 }] },
    { ssid: "[Smart_Fridge]a1b2", auth: "WPA2-Personal", aps: [{ b: 2.4, ch: 11, s: 32 }] },
    { ssid: "Workshop12", auth: "WPA2-Personal", aps: [{ b: 2.4, ch: 11, s: 14 }, { b: 5, ch: 149, s: 14 }] },
    { ssid: "CEDAR-12", auth: "WPA2-Personal", aps: [{ b: 2.4, ch: 11, s: 14 }, { b: 5, ch: 149, s: 14 }] },
    { ssid: "", auth: "WPA2-Personal", aps: [{ b: 5, ch: 149, s: 6 }] },
  ];
  if (window.MOCK_HOSTILE) NETS.push({ ssid: "<img src=x onerror=alert(1)>", auth: "Open", aps: [{ b: 2.4, ch: 1, s: 9 }] });
  const PROFILES = {
    unigen: new Set(["HOME-5G", "Maple House", "oldrouter", "Guest_net 2", "phone_hotspot", "Cafe_wifi", "Guest_net"]),
    builtin: new Set(["HOME-5G", "phone_hotspot", "Cafe_wifi", "Guest_net 2", "Guest_net"]),
  };
  const SEC = { "WPA2-Personal": "WPA2", "Open": "Open" };
  let WIFI = "unigen", RADIO = "unigen"; // the adapter Wi-Fi uses (the other one's Wi-Fi is switched off, unless MOCK_BOTH_ON) and the one Bluetooth uses
  let POWER = window.MOCK_BT_OFF ? "off" : "on", searchTimers = [], answer = null;
  const PAIRED = [
    { id: "BT-beats", name: "Den Beats Pill", connected: true, kind: "Speaker", address: "A1B2C3D4E5F1", lastBattery: 90 },
    { id: "BT-nord", name: "OnePlus Nord Buds 3r", connected: false, kind: "Headphones", address: "A1B2C3D4E5F2" },
    { id: "BT-jbl", name: "JBL Go 3", connected: false, kind: "Speaker", address: "A1B2C3D4E5F3", lastBattery: 15 },
    { id: "BT-tribit", name: "Tribit StormBox Mini+", connected: false, kind: "Speaker", address: "A1B2C3D4E5F4" },
    { id: "BT-mhx", name: "MHX-BT88", connected: false, kind: "Audio", address: "A1B2C3D4E5F5" },
    { id: "BT-dualsense", name: "DualSense Wireless Controller", connected: false, kind: "Controller", address: "A1B2C3D4E5F6" },
  ];
  const NEARBY = [
    { id: "BT-buds2", name: "Galaxy Buds2 Pro", kind: "Headphones", address: "B1B2C3D4E5F1", ceremony: null },
    { id: "BT-boat", name: "boAt Stone 350", kind: "Speaker", address: "B1B2C3D4E5F2", ceremony: null },
    { id: "BT-mi", name: "Mi Portable Speaker", kind: "Speaker", address: "B1B2C3D4E5F3", ceremony: null },
    { id: "BT-pixel", name: "Pixel 8", kind: "Phone", address: "B1B2C3D4E5F4", ceremony: "confirm" },
    { id: "BT-k380", name: "Keys-To-Go K3", kind: "Keyboard", address: "B1B2C3D4E5F5", ceremony: "display" },
    { id: "BT-car", name: "Car Kit 2", kind: "Audio", address: "B1B2C3D4E5F6", ceremony: "provide" },
  ];
  if (window.MOCK_HOSTILE) NEARBY.push({ id: "BT-evil2", name: "<img src=x onerror=alert(2)>", kind: "Device", address: "B1B2C3D4E5F7", ceremony: "confirm" });

  if (window.MOCK_OTHER_RADIO) PAIRED.filter(d => d.id === "BT-nord" || d.id === "BT-jbl").forEach(d => { d.here = false; });
  if (window.MOCK_HOSTILE) {
    PROFILES.unigen.add("<img src=x onerror=alert(1)>");
    PAIRED.push({ id: "BT-evil", name: "<img src=x onerror=alert(1)>", connected: false, kind: "Audio", address: "A1B2C3D4E5F7" });
  }

  // speed: 28 download + 12 upload samples, ramping up at the start of each phase (like speed.py)
  const sample = (i, dl, ul) => {
    const up = i >= 28, k = up ? i - 28 : i;
    return +((up ? ul : dl) * Math.min(1, (k + 1) / 5) * (0.85 + Math.random() * 0.3)).toFixed(1);
  };
  const avg = xs => Math.round(xs.slice(3).reduce((a, b) => a + b, 0) / Math.max(1, xs.length - 3));
  const stamp = () => { const d = new Date(), p = n => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };
  const result = (samples, link, at) => ({ ping: 2, down: avg(samples.slice(0, 28)), up: avg(samples.slice(28)), samples, split: 28, at, link });
  const BASE = { unigen: [50, 12], builtin: [53, 31] };
  const RESULTS = {};
  for (const k of ["unigen", "builtin"]) RESULTS[k] = result(Array.from({ length: 40 }, (_, i) => sample(i, ...BASE[k])), k === "unigen" ? 433 : 866, "2026-10-12 23:00");

  const plugged = () => ADAPTERS.filter(a => a.key !== window.MOCK_UNPLUG);
  const pick = key => (plugged().find(a => a.key === key) || plugged()[0]).key; // unplugging the dongle falls back, like the watchdog
  const using = () => pick(WIFI), radio = () => pick(RADIO);
  const off = a => !window.MOCK_BOTH_ON && a.key !== using();
  const live = () => plugged().filter(a => !off(a)); // adapters with a Wi-Fi interface right now
  const adapter = key => {
    const a = live().find(x => x.key === key);
    if (!a) throw new Error(`The ${NAMES[key] || key} isn't plugged in.`);
    return a;
  };
  const shape = a => {
    const nets = NETS.map(n => ({
      ssid: n.ssid, sec: SEC[n.auth] || n.auth, auth: n.auth, hidden: !n.ssid,
      state: n.ssid && a.state === "connected" && a.ssid === n.ssid ? "Connected" : PROFILES[a.key].has(n.ssid) ? "Saved" : "",
      aps: n.aps.map(x => ({ ...x, s: Math.max(1, x.s - (a.key === "builtin" ? 12 : 0)) })),
    }));
    const best = n => Math.max(0, ...n.aps.map(x => x.s));
    nets.sort((x, y) => (x.state !== "Connected") - (y.state !== "Connected") || best(y) - best(x));
    return { networks: nets, scanned_at: Date.now() / 1000 };
  };

  def("app_info", 0, () => ({ version: "0.0.0-mock", admin: window.MOCK_ADMIN !== false, wifi_using: using(),
    adapters: plugged().map(a => ({ key: a.key, name: a.name, wifi: off(a) ? null : "Wi-Fi 6", bt: a.bt, using: a.key === using(), off: off(a) })) }));
  def("adapters", 0, () => live().map(a => {
    const on = a.state === "connected";
    return { key: a.key, name: a.name, state: a.state, ssid: on ? a.ssid : null, rate: on ? a.rate : null, channel: a.channel, band: a.band,
             signal: on ? Math.max(50, Math.min(100, a.signal + Math.round(Math.random() * 4 - 2))) : null };
  }));
  def("networks", 200, key => shape(adapter(key)));
  def("scan", 1600, key => shape(adapter(key)));
  def("connect", 1600, (key, ssid, password) => {
    const a = adapter(key), n = NETS.find(x => x.ssid === ssid);
    if (!n) throw new Error(`${ssid} is out of range.`);
    if (!PROFILES[key].has(ssid)) {
      if (n.auth !== "Open" && !(typeof password === "string" && password.length >= 8 && password.length <= 63)) throw new Error("The password must be 8 to 63 characters.");
      if (password === "wrongpass") throw new Error(`Couldn't connect to ${ssid}. Check the password.`);
      PROFILES[key].add(ssid);
    }
    const five = n.aps.some(x => x.b === 5);
    Object.assign(a, { state: "connected", ssid, rate: five ? (key === "unigen" ? 433 : 866) : (key === "unigen" ? 144 : 287) });
    return { ssid, rate: a.rate };
  });
  def("disconnect", 1000, key => { adapter(key).state = "disconnected"; });
  def("saved", 100, () => {
    const out = new Map();
    for (const a of live()) for (const s of PROFILES[a.key]) out.set(s, [...(out.get(s) || []), a.key]);
    return [...out].map(([ssid, on]) => ({ ssid, on }));
  });
  def("password", 150, ssid => {
    if (!Object.values(PROFILES).some(p => p.has(ssid))) throw new Error(`${ssid} isn't saved on this PC.`);
    return "mock-pass-1234";
  });
  def("copy_profile", 1200, (ssid, src, dst) => { adapter(src); adapter(dst); PROFILES[dst].add(ssid); });
  def("delete_profile", 300, ssid => { Object.values(PROFILES).forEach(p => p.delete(ssid)); });
  const row = d => ({ id: d.id, ids: [d.id], name: d.name, kind: d.kind, connected: !!d.connected, address: d.address, here: true });
  const otherName = () => NAMES[radio() === "unigen" ? "builtin" : "unigen"];
  // a paired device as bt_paired lists it; one paired only on the other radio also names both radios
  const view = ({ lastBattery, here, ...d }) => ({ ...d, ids: d.ids || [d.id], battery: d.connected ? lastBattery ?? null : null, here: here !== false,
    ...(here === false && { radio_name: otherName(), here_name: NAMES[radio()] }) });
  const push = (devices, done) => window.onBtNearby && window.onBtNearby({ devices: devices.map(row), done });
  def("bt_radio", 100, () => ({ active: radio(), can_switch: window.MOCK_ADMIN !== false, power: POWER,
    radios: plugged().map(a => ({ key: a.key, name: a.name, ok: a.key === radio(), disabled: a.key !== radio(), version: a.bt })) }));
  def("bt_power", 600, on => { POWER = on ? "on" : "off"; return { power: POWER }; });
  def("bt_paired", 200, () => PAIRED.map(view));
  def("bt_search_start", 100, () => {
    if (POWER === "off") throw new Error("Bluetooth is off. Turn it on first.");
    searchTimers.forEach(clearTimeout); searchTimers = [];
    const todo = NEARBY.filter(d => !PAIRED.some(p => p.id === d.id)), step = window.MOCK_FAST ? 0 : 400;
    todo.forEach((d, i) => searchTimers.push(setTimeout(() => push(todo.slice(0, i + 1), false), step * (i + 1))));
    if (!window.MOCK_SEARCH_HOLD) searchTimers.push(setTimeout(() => push(todo, true), step * (todo.length + 1)));
  });
  def("bt_search_stop", 0, () => { searchTimers.forEach(clearTimeout); searchTimers = []; });
  def("bt_pair_answer", 0, (accept, pin) => { if (answer) answer({ accept, pin }); });
  def("bt_pair", 1400, async id => {
    const away = PAIRED.find(x => x.id === id && x.here === false);
    if (away) { // paired on the other radio only: pairing again through this one, then it connects
      away.here = true; away.connected = ["Headphones", "Speaker", "Audio"].includes(away.kind);
      return view(away);
    }
    const d = NEARBY.find(x => x.id === id);
    if (!d) throw new Error("The device didn't answer. Bring it closer and make sure it's in pairing mode.");
    if (d.ceremony) {
      const reply = new Promise(r => { answer = r; });
      window.onPairPrompt && window.onPairPrompt({ kind: d.ceremony, pin: d.ceremony === "provide" ? "" : "482913" });
      if (d.ceremony !== "display") {
        const { accept, pin } = await reply; answer = null;
        if (!accept) throw new Error("Pairing cancelled.");
        if (d.ceremony === "provide" && pin !== "0000") throw new Error("Wrong PIN. Try again.");
      } else { answer = null; await new Promise(r => setTimeout(r, 300)); } // real delay even under MOCK_FAST: the prompt must stay up long enough to see
    }
    const p = { ...row(d), connected: ["Headphones", "Speaker", "Audio"].includes(d.kind) };
    if (window.MOCK_PAIR_TWIN) {
      // a dual-mode device: Windows lists it under its classic id, the page refreshes mid-pairing, and the answer
      // still carries the LE id the search found (Windows hadn't listed the classic record yet when it was read)
      PAIRED.push({ ...p, id: `${d.id}-classic`, ids: [`${d.id}-classic`, d.id] });
      if (window.loadBt) await window.loadBt();
      return p;
    }
    PAIRED.push(p);
    return p;
  });
  def("bt_remove", 500, id => { const i = PAIRED.findIndex(d => d.id === id); if (i >= 0) PAIRED.splice(i, 1); });
  def("bt_connect", 1400, id => {
    const d = PAIRED.find(x => x.id === id);
    if (!d) throw new Error("That device isn't paired any more.");
    if (d.here === false) throw new Error(`${d.name} is paired with the ${otherName()}, not this one. Put it in pairing mode, then press Re-pair.`);
    d.connected = true;
  });
  def("bt_disconnect", 1000, id => { const d = PAIRED.find(x => x.id === id); if (!d) throw new Error("That device isn't paired any more."); d.connected = false; });
  def("speed_test", 0, async key => {
    const a = adapter(key);
    if (a.state !== "connected") throw new Error("That adapter isn't connected to a network.");
    const samples = [];
    for (let i = 0; i < 40; i++) {
      const v = sample(i, ...BASE[key]);
      samples.push(v);
      if (window.onSpeedSample) window.onSpeedSample({ phase: i >= 28 ? "up" : "down", v });
      await wait(75);
    }
    return (RESULTS[key] = result(samples, a.rate, stamp()));
  });
  def("speed_results", 0, () => JSON.parse(JSON.stringify(RESULTS)));
  // tray widget
  const need = () => { if (window.MOCK_ADMIN === false) throw new Error("Switching adapters needs administrator rights. Restart the app and choose Yes."); };
  const say = (kind, text, done, error = false) => window.onSwitchStep && window.onSwitchStep({ kind, text, done, error });
  def("switch_wifi", 0, async key => {
    need();
    const t = plugged().find(a => a.key === key);
    if (!t) throw new Error(`The ${NAMES[key] || key} isn't plugged in.`);
    const old = plugged().find(a => a.key !== key);
    for (const text of [`Turning on the ${t.name}…`, "Connecting to HOME-5G…"]) {
      say("wifi", text, false);
      await wait(300);
    }
    WIFI = key;
    t.state = "connected"; t.ssid = "HOME-5G";
    say("wifi", `Done. Using the ${t.name}.`, true);
    if (old) wait(600).then(() => say("wifi", `The ${old.name} is off.`, true));  // like hw: the old Wi-Fi goes off after the switch reports done
    return { using: key };
  });
  def("switch_bt", 0, async key => {
    need();
    const t = plugged().find(a => a.key === key);
    if (!t) throw new Error(`The ${NAMES[key] || key} isn't plugged in.`);
    say("bt", `Moving Bluetooth to the ${t.name}. This can take up to a minute.`, false);
    wait(600).then(() => {  // like hw: the move ends in the background
      if (window.MOCK_BT_FAIL) return say("bt", window.MOCK_BT_FAIL, true, true);
      RADIO = key;
      say("bt", `Bluetooth moved to the ${t.name}.`, true);
    });
    return { using: key };
  });
  def("is_visible", 0, which => true);
  def("open_main", 0, () => null);
  def("hide_widget", 0, () => null);
  def("widget_fit", 0, () => null);
  api._setUsing = (key, kind) => { if (kind !== "bt") WIFI = key; if (kind !== "wifi") RADIO = key; }; // test hook
  api._setConnected = (id, on) => { PAIRED.find(d => d.id === id).connected = on; }; // test hook
  api._setHere = (id, on) => { PAIRED.find(d => d.id === id).here = on; }; // test hook
  return api;
})();
