// Stand-in for api.py when the page is opened as index.html?mock (browser preview and UI tests).
// Same method names and data shapes as the Python Api; tests/test_api.py checks that the names match.
// Test hooks (set before the page loads): MOCK_FAST (no delays), MOCK_FAIL = { method: "message" },
// MOCK_UNPLUG = "unigen" | "builtin", MOCK_ADMIN = false, MOCK_HOSTILE (adds a network, saved profile and paired device named like an HTML tag).
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
  const RADIOS = [
    { key: "unigen", name: NAMES.unigen, ok: true, disabled: false, version: "5.4" },
    { key: "builtin", name: NAMES.builtin, ok: false, disabled: true, version: "5.2" },
  ];
  const PAIRED = [
    { id: "BT-beats", name: "Den Beats Pill", connected: true, kind: "Speaker", address: "A1B2C3D4E5F1" },
    { id: "BT-nord", name: "OnePlus Nord Buds 3r", connected: false, kind: "Headphones", address: "A1B2C3D4E5F2" },
    { id: "BT-jbl", name: "JBL Go 3", connected: false, kind: "Speaker", address: "A1B2C3D4E5F3" },
    { id: "BT-tribit", name: "Tribit StormBox Mini+", connected: false, kind: "Speaker", address: "A1B2C3D4E5F4" },
    { id: "BT-mhx", name: "MHX-BT88", connected: false, kind: "Audio", address: "A1B2C3D4E5F5" },
    { id: "BT-dualsense", name: "DualSense Wireless Controller", connected: false, kind: "Controller", address: "A1B2C3D4E5F6" },
  ];
  const NEARBY = [
    { id: "BT-buds2", name: "Galaxy Buds2 Pro", connected: false, kind: "Headphones", address: "B1B2C3D4E5F1" },
    { id: "BT-boat", name: "boAt Stone 350", connected: false, kind: "Speaker", address: "B1B2C3D4E5F2" },
    { id: "BT-mi", name: "Mi Portable Speaker", connected: false, kind: "Speaker", address: "B1B2C3D4E5F3" },
  ];

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
  const adapter = key => {
    const a = plugged().find(x => x.key === key);
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

  def("app_info", 0, () => ({ version: "0.0.0-mock", admin: window.MOCK_ADMIN !== false, adapters: plugged().map(a => ({ key: a.key, name: a.name, wifi: "Wi-Fi 6", bt: a.bt })) }));
  def("adapters", 0, () => plugged().map(a => {
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
    for (const a of plugged()) for (const s of PROFILES[a.key]) out.set(s, [...(out.get(s) || []), a.key]);
    return [...out].map(([ssid, on]) => ({ ssid, on }));
  });
  def("password", 150, ssid => {
    if (!Object.values(PROFILES).some(p => p.has(ssid))) throw new Error(`${ssid} isn't saved on this PC.`);
    return "mock-pass-1234";
  });
  def("copy_profile", 1200, (ssid, src, dst) => { adapter(src); adapter(dst); PROFILES[dst].add(ssid); });
  def("delete_profile", 300, ssid => { Object.values(PROFILES).forEach(p => p.delete(ssid)); });
  def("bt_radio", 100, () => ({ active: (RADIOS.find(r => r.ok) || {}).key ?? null, can_switch: window.MOCK_ADMIN !== false, radios: RADIOS.map(r => ({ ...r })) }));
  def("bt_switch", 2500, key => {
    if (window.MOCK_ADMIN === false) throw new Error("Bluetooth radio switching needs administrator rights. Restart the app and choose Yes.");
    RADIOS.forEach(r => { r.ok = r.key === key; r.disabled = !r.ok; });
    return { active: key };
  });
  def("bt_paired", 200, () => PAIRED.map(d => ({ ...d })));
  def("bt_nearby", 3000, () => NEARBY.filter(d => !PAIRED.some(p => p.id === d.id)).map(d => ({ ...d })));
  def("bt_pair", 1400, id => {
    const d = NEARBY.find(x => x.id === id);
    if (!d) throw new Error("The device didn't answer in time. Put it in pairing mode and try again.");
    PAIRED.push({ ...d, connected: false });
  });
  def("bt_remove", 500, id => { const i = PAIRED.findIndex(d => d.id === id); if (i >= 0) PAIRED.splice(i, 1); });
  def("bt_connect", 1400, id => { const d = PAIRED.find(x => x.id === id); if (!d) throw new Error("That device isn't paired any more."); d.connected = true; });
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
  def("use_adapter", 1400, key => {
    const t = adapter(key), others = plugged().filter(a => a.key !== key);
    const net = t.state === "connected" ? t.ssid : (others.find(a => a.state === "connected") || {}).ssid;
    if (!net) throw new Error("Neither adapter is connected. Connect to a network first.");
    PROFILES[key].add(net);
    const n = NETS.find(x => x.ssid === net), five = !n || n.aps.some(x => x.b === 5);
    Object.assign(t, { state: "connected", ssid: net, rate: five ? (key === "unigen" ? 433 : 866) : (key === "unigen" ? 144 : 287) });
    others.forEach(a => { a.state = "disconnected"; });
    return { key, ssid: net };
  });
  def("is_visible", 0, which => true);
  def("open_main", 0, () => null);
  def("hide_widget", 0, () => null);
  def("widget_fit", 0, () => null);
  return api;
})();
