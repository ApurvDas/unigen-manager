// Stand-in for api.py when the page is opened as index.html?mock (browser preview and UI tests).
// Same method names and data shapes as the Python Api; tests/test_api.py checks that the names match.
// Test hooks (set before the page loads): MOCK_FAST (no delays), MOCK_FAIL = { method: "message" },
// MOCK_UNPLUG = "unigen" | "builtin", MOCK_DONGLE = "unplugged" | "not_responding" (the dongle's status; "unplugged" removes it like MOCK_UNPLUG = "unigen"), MOCK_ADMIN = false, MOCK_HOSTILE (adds a network, saved profile and paired device named like an HTML tag),
// MOCK_SEARCH_HOLD (the Bluetooth search never finishes), MOCK_PAIR_TWIN (pairing races a paired-list refresh), MOCK_BT_OFF (Bluetooth starts off),
// MOCK_BOTH_ON (neither adapter is switched off, like before the first switch), MOCK_TRAFFIC = "none" (no Wi-Fi adapter is on) | "measuring" (the first second: no rate yet), MOCK_OTHER_RADIO (two paired devices are paired
// only with the other radio: Re-pair instead of Connect), MOCK_BT_FAIL = "message" (the background Bluetooth move fails) and
// MOCK_WIFI_FAIL = "message" (the Wi-Fi switch fails), both at step MOCK_FAIL_STEP (default 2); MOCK_HOLD_STEP = n (a move waits
// after announcing step n until mockApi._resume(), to look at a step or test it without timing).
// Switches play the real step sequences of hw.py (5 Wi-Fi steps, 4 Bluetooth ones), each step 300-800 ms unless MOCK_FAST.
// MOCK_DRIVER = "missing" (the dongle is plugged in but has no Wi-Fi driver: app_info says "no_driver" and install_driver plays the five steps
// of driver.py, after which the dongle works; cancel_driver stops the download); MOCK_DRIVER_FAIL = "message" fails the install at step MOCK_FAIL_STEP (default 2);
// window.mockApi._setUsing(key, kind) changes the adapter Wi-Fi ("wifi") or Bluetooth ("bt") uses, both without a kind;
// mockApi._setDongle(state) plugs the dongle in ("connected"), out ("unplugged") or hangs it ("not_responding");
// MOCK_WIRED (adds Ethernet and USB tethering, both up: they show in Merge connections and in the Traffic page; tethering starts out of merge, like the
// real app) and MOCK_MERGE (merge starts on). mockApi._unplug(key) takes one of those two away, mockApi._plug(key) brings it back.
// mockApi._setConnected(id, on) connects a paired device behind the app's back (as Windows Settings would);
// mockApi._setHere(id, on) moves a paired device to / from the other radio behind the app's back;
// mockApi._setRate(down, up) holds the adapter in use at fixed bytes per second (history included), instead of the bursty synthetic traffic.
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

  let DRIVER = window.MOCK_DRIVER || "installed", cancelled = false;  // the dongle's Wi-Fi driver; "missing" until install_driver has played
  const dongle = () => window.MOCK_UNPLUG === "unigen" ? "unplugged" : DRIVER === "missing" ? "no_driver" : window.MOCK_DONGLE || "connected";
  const plugged = () => ADAPTERS.filter(a => a.key !== window.MOCK_UNPLUG && !(a.key === "unigen" && ["unplugged", "no_driver"].includes(dongle())));
  const pick = key => (plugged().find(a => a.key === key) || plugged()[0]).key; // unplugging the dongle falls back, like the watchdog
  const using = () => pick(WIFI), radio = () => pick(RADIO);
  // merge connections: the Wi-Fi adapters and, with MOCK_WIRED, Ethernet and USB tethering; CHOICE is the user's saved choice per link
  let MERGE = !!window.MOCK_MERGE;
  const CHOICE = {}, GONE = new Set();
  const WIRED = [{ key: "ethernet:mock", kind: "ethernet", name: "Ethernet", detail: "Realtek PCIe GbE Family Controller", ip: "192.168.0.20" },
    { key: "tether:mock", kind: "tether", name: "USB tethering (phone)", detail: "Remote NDIS based Internet Sharing Device", ip: "192.168.42.129" }];
  const wired = () => window.MOCK_WIRED ? WIRED.filter(w => !GONE.has(w.key)) : [];
  const inMerge = (key, kind = "wifi") => CHOICE[key] ?? kind !== "tether";
  const off = a => !window.MOCK_BOTH_ON && !(MERGE && inMerge(a.key)) && a.key !== using();
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

  def("app_info", 0, () => ({ version: "0.0.0-mock", admin: window.MOCK_ADMIN !== false, wifi_using: using(), dongle: dongle(),
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
  def("merge_status", 0, () => {
    trafficTo(Date.now());
    const rate = key => { const h = TRAFFIC.hist[key], last = h && h[h.length - 1]; return last ? last : [null, null]; };
    const links = [...plugged().map(a => ({ key: a.key, kind: "wifi", name: a.name, detail: "", ip: off(a) ? null : a.key === "unigen" ? "192.168.1.5" : "192.168.1.7", online: !off(a) })),
      ...wired().map(w => ({ key: w.key, kind: w.kind, name: w.name, detail: w.detail, ip: w.ip, online: true }))].map(l => {
      const included = inMerge(l.key, l.kind), [down, up] = l.online ? rate(l.key) : [null, null];
      return { ...l, included, state: !included ? "off" : !l.online ? "down" : MERGE ? "up" : "checking", active: MERGE && included && l.online ? 2 : 0,
        opened: MERGE && included && l.online ? 40 : 0, down, up };
    });
    const usable = links.filter(l => l.included && l.online), wifi = usable.filter(l => l.kind === "wifi");
    return { on: MERGE, port: MERGE ? 18780 : null, wcm: MERGE, can_switch: window.MOCK_ADMIN !== false, links, single: MERGE && usable.length < 2,
      same_network: MERGE && wifi.length === 2 ? "HOME-5G" : null };
  });
  def("set_merge", 600, on => {
    need("Merging connections");
    MERGE = !!on;
    window.onMerge && window.onMerge();
    return { on: MERGE };
  });
  def("set_merge_link", 200, (key, on) => {
    if (![...plugged().map(a => a.key), ...wired().map(w => w.key)].includes(key)) throw new Error("That connection isn't here any more.");
    CHOICE[key] = !!on;
    window.onMerge && window.onMerge();
    return { key, on: !!on };
  });
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
    if (moving === "bt") throw new Error("Bluetooth isn't ready yet. If you just switched adapters, it's still moving: try again in a moment.");
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
  const need = (what = "Switching adapters") => { if (window.MOCK_ADMIN === false) throw new Error(`${what} needs administrator rights. Restart the app and choose Yes.`); };
  // like api.Mover: each step carries step/of/label, and a done step names the step the move stopped at
  const say = (kind, text, done = false, error = false, step = null, of = null, label = null) =>
    window.onSwitchStep && window.onSwitchStep({ kind, text, done, error, step, of, label });
  let moving = null, gate = null;  // the kind of move running (one lock for both); gate: a move held by MOCK_HOLD_STEP
  const failAt = () => window.MOCK_FAIL_STEP || 2;
  const hold = n => window.MOCK_HOLD_STEP === n ? new Promise(r => { gate = r; }) : null;
  const busy = () => { if (moving) throw new Error("A switch is still finishing. Bluetooth can take up to a minute; try again in a moment."); };
  // Plays steps [[n, label, ms, effect]] of `of`: announce, wait, apply. Returns the step it failed at (after saying so), or 0.
  async function play(kind, steps, of, failText) {
    for (const [n, label, ms, effect] of steps) {
      say(kind, `${label}…`, false, false, n, of, label);
      await hold(n);
      await wait(ms);
      if (failText && n >= failAt()) { moving = null; say(kind, failText, true, true, n, of, label); return n; }
      if (effect) effect();
    }
    return 0;
  }
  def("switch_wifi", 0, async key => {
    need();
    const t = plugged().find(a => a.key === key);
    if (!t) throw new Error(`The ${NAMES[key] || key} isn't plugged in.`);
    busy();
    const old = plugged().find(a => a.key !== key);
    const labels = [`Turning on the ${t.name}`, "Waiting for it to start", ...(old ? ["Finding HOME-5G", "Connecting to HOME-5G"] : []),
      ...(old ? [`Turning off the ${old.name}`] : [])];
    const of = labels.length, steps = labels.map((label, i) => [i + 1, label, 300]);
    moving = "wifi";
    const failed = await play("wifi", old ? steps.slice(0, -1) : steps, of, window.MOCK_WIFI_FAIL);
    if (failed) throw new Error(window.MOCK_WIFI_FAIL);
    WIFI = key;
    t.state = "connected"; t.ssid = "HOME-5G";
    const end = () => { moving = null; say("wifi", `Wi-Fi moved to the ${t.name}.`, true, false, of, of, labels[of - 1]); };
    if (!old) end();
    else (async () => {  // like hw: the old Wi-Fi goes off after the switch call returns
      say("wifi", `${labels[of - 1]}…`, false, false, of, of, labels[of - 1]);
      await hold(of);
      await wait(600);
      end();
    })();
    return { using: key };
  });
  def("switch_bt", 0, async key => {
    need();
    const t = plugged().find(a => a.key === key);
    if (!t) throw new Error(`The ${NAMES[key] || key} isn't plugged in.`);
    busy();
    const old = plugged().find(a => a.key !== key), held = PAIRED.filter(d => d.connected);
    moving = "bt";
    say("bt", `Moving Bluetooth to the ${t.name}. This can take up to a minute.`, false, false, 0, 4, "Starting");
    const set = on => () => held.forEach(d => { d.connected = on; });
    (async () => {  // like hw: the move runs in the background; a phase with nothing to do is skipped
      const steps = [held.length && [1, "Disconnecting your devices", 500, set(false)], old && [2, `Turning off the ${old.name} radio`, 800],
        [3, `Starting the ${t.name} radio`, 800], held.length && [4, "Reconnecting your devices", 600, set(true)]].filter(Boolean);
      if (await play("bt", steps, 4, window.MOCK_BT_FAIL)) return set(true)();  // the failed move leaves the devices connected as before
      RADIO = key;
      moving = null;
      say("bt", `Bluetooth moved to the ${t.name}.`, true, false, steps[steps.length - 1][0], 4, steps[steps.length - 1][1]);
    })();
    return { using: key };
  });
  // dongle driver: the five steps of driver.install; the download reports its running figures as the same step again
  def("driver_status", 0, () => ({ state: window.MOCK_UNPLUG === "unigen" || window.MOCK_DONGLE === "unplugged" ? "absent" : DRIVER, loader: false,
    can_install: window.MOCK_ADMIN !== false }));
  def("install_driver", 0, async () => {
    need("Installing the driver");
    if (DRIVER !== "missing") throw new Error("The dongle already has its Wi-Fi driver.");
    busy();
    const of = 5, SLICE_MS = 250, STEP_MS = 600, INSTALL_MS = 1500, SLICES = 6, MB = 3.3;  // the download is MB in SLICES slices
    const LABELS = ["Downloading", "Verifying", "Unpacking", "Installing", "Checking"], TEXT = ["Downloading the driver", "Checking the download", "Unpacking the driver", "Installing the driver", "Starting the dongle's Wi-Fi"];
    const fail = (n, text) => { moving = null; say("driver", text, true, true, n, of, LABELS[n - 1]); throw new Error(text); };
    moving = "driver"; cancelled = false;
    say("driver", `${TEXT[0]}…`, false, false, 1, of, LABELS[0]);
    await hold(1);
    for (let i = 1; i <= SLICES; i++) {
      await wait(SLICE_MS);
      if (cancelled) fail(1, "Cancelled. Nothing was installed.");
      say("driver", `${TEXT[0]}… ${(i * MB / SLICES).toFixed(1)} of ${MB} MB`, false, false, 1, of, `${LABELS[0]} ${(i * MB / SLICES).toFixed(1)} of ${MB} MB`);
    }
    if (window.MOCK_DRIVER_FAIL && failAt() <= 1) fail(1, window.MOCK_DRIVER_FAIL);
    for (let n = 2; n <= of; n++) {
      say("driver", `${TEXT[n - 1]}…`, false, false, n, of, LABELS[n - 1]);
      await hold(n);
      await wait(n === 4 ? INSTALL_MS : STEP_MS);
      if (window.MOCK_DRIVER_FAIL && n >= failAt()) fail(n, window.MOCK_DRIVER_FAIL);
    }
    DRIVER = "installed"; moving = null;
    say("driver", "Driver installed. The dongle's Wi-Fi is ready.", true, false, of, of, LABELS[of - 1]);
    return { state: "installed", loader: false };
  });
  def("cancel_driver", 0, () => { cancelled = true; });
  // traffic: a synthetic sampler, one reading per wall-clock second. The adapter in use pulls bursty 1-8 MB/s down and a few hundred
  // KB/s up; the other one idles. Same shapes as traffic.Sampler: 60 readings of [down, up], today's totals, a tick counter.
  let UNIT = "bytes", fixed = null;
  const TRAFFIC = { sec: null, hist: { unigen: [], builtin: [] }, today: { unigen: { down: 3.84e9, up: 2.1e8 }, builtin: { down: 2.4e8, up: 1.1e7 } } };
  if (window.MOCK_WIRED) {  // Ethernet moves about as much as the adapter in use, the phone a little
    TRAFFIC.hist["ethernet:mock"] = []; TRAFFIC.hist["tether:mock"] = [];
    TRAFFIC.today["ethernet:mock"] = { down: 1.2e9, up: 6e7 }; TRAFFIC.today["tether:mock"] = { down: 3e7, up: 2e6 };
  }
  const synth = (busy, t) => busy
    ? [Math.max(3e5, 4.2e6 + 2.6e6 * Math.sin(t / 7) + 1.4e6 * Math.sin(t / 2.3 + 1) + 0.6e6 * Math.sin(t * 1.7)), Math.max(2e4, 3e5 + 1.6e5 * Math.sin(t / 5 + 2) + 0.7e5 * Math.sin(t * 1.3))]
    : [1.5e4 * (1.2 + Math.sin(t / 3)), 4e3 * (1.2 + Math.sin(t / 4))];
  function trafficTo(now) {
    const sec = Math.floor(now / 1000), busyKey = using();
    for (let t = TRAFFIC.sec === null ? sec - 59 : TRAFFIC.sec + 1; t <= sec; t++) {
      for (const k of Object.keys(TRAFFIC.hist)) {
        const [d, u] = fixed && k === busyKey ? fixed : synth(k === busyKey, t).map(v => k === "tether:mock" ? v / 4 : v), h = TRAFFIC.hist[k];
        h.push([Math.round(d), Math.round(u)]);
        if (h.length > 60) h.shift();
        if (TRAFFIC.sec !== null) { TRAFFIC.today[k].down += Math.round(d); TRAFFIC.today[k].up += Math.round(u); }
      }
    }
    TRAFFIC.sec = sec;
    return sec;
  }
  def("traffic", 0, () => {
    const sec = trafficTo(Date.now()), none = window.MOCK_TRAFFIC === "none", first = window.MOCK_TRAFFIC === "measuring";
    const ads = [...plugged().map(a => ({ key: a.key, kind: "wifi", name: a.name })), ...wired().map(w => ({ key: w.key, kind: w.kind, name: w.name }))];
    return { using: none ? null : using(), unit: UNIT, tick: sec % 1e6,
      adapters: none ? [] : ads.map(a => { const h = TRAFFIC.hist[a.key], last = h[h.length - 1];
        return { ...a, down: first ? null : last[0], up: first ? null : last[1], history: first ? [] : h.map(x => [...x]) }; }),
      today: none ? {} : Object.fromEntries(ads.map(a => [a.key, { ...TRAFFIC.today[a.key] }])) };
  });
  def("set_traffic_unit", 0, unit => {
    if (unit !== "bytes" && unit !== "bits") throw new Error("The unit must be bytes or bits.");
    UNIT = unit;
    window.onTrafficUnit && window.onTrafficUnit(unit);
    return { unit };
  });
  def("is_visible", 0, which => true);
  def("open_main", 0, () => null);
  def("hide_widget", 0, () => null);
  def("widget_fit", 0, () => null);
  api._resume = () => { const g = gate; gate = null; if (g) g(); }; // test hook: let a move held by MOCK_HOLD_STEP go on
  api._setDongle = state => { window.MOCK_DONGLE = state; if (window.MOCK_UNPLUG === "unigen") window.MOCK_UNPLUG = undefined; }; // test hook
  api._setUsing = (key, kind) => { if (kind !== "bt") WIFI = key; if (kind !== "wifi") RADIO = key; }; // test hook
  api._setConnected = (id, on) => { PAIRED.find(d => d.id === id).connected = on; }; // test hook
  api._setHere = (id, on) => { PAIRED.find(d => d.id === id).here = on; }; // test hook
  api._unplug = key => { GONE.add(key); }; // test hook: Ethernet or USB tethering goes away
  api._plug = key => { GONE.delete(key); }; // test hook
  api._setRate = (down, up) => { // test hook
    fixed = [down, up]; trafficTo(Date.now());
    TRAFFIC.hist[using()] = Array.from({ length: 60 }, () => [down, up]);
  };
  return api;
})();
