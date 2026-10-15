"""What the page calls (window.pywebview.api). Every public method returns {"ok", "data"} or {"ok", "error"}.
pywebview runs each call on its own thread, so slow work never blocks the window."""
import functools, json, logging, os, threading, time, traceback
from pathlib import Path

import bt, hw, speed, tray, wifi, winrun
from version import VERSION

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "UnigenManager"
log = logging.getLogger("unigen")
PAIR_WAIT = 60  # seconds a pairing prompt waits for the user
_KNOWN = (wifi.WifiError, wifi.ParseError, bt.BtError, hw.HwError, speed.SpeedError, winrun.CmdError)
_SEC = {"WPA2-Personal": "WPA2", "WPA3-Personal": "WPA3", "Open": "Open", "WPA-Personal": "WPA", "WPA2-Enterprise": "WPA2-Ent"}


# The page polls these every few seconds: logged only with --debug, or when slow or failing
_POLLED = {"app_info", "adapters", "networks", "saved", "bt_radio", "bt_paired", "is_visible", "widget_fit", "speed_results"}
_SECRET = {"connect": 2, "bt_pair_answer": 1}  # argument index never written to app.log (return values never are)
SLOW = 3.0  # seconds; a polled call taking longer is logged as a warning


def _args(name, args):
    hide = _SECRET.get(name)
    return ", ".join("***" if i == hide and a is not None else repr(a) for i, a in enumerate(args))


def _where(e):
    """Where an error was raised: the last few frames, innermost last, e.g. 'hw.py:236 _use > wifi.py:88 connect'."""
    frames = traceback.extract_tb(e.__traceback__)[1:][-4:]  # [1:] drops this wrapper's own frame
    return " > ".join(f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in frames)


def _envelope(fn):
    name = fn.__name__

    @functools.wraps(fn)
    def wrapper(self, *args):
        call, t0 = f"{name}({_args(name, args)})", time.monotonic()
        try:
            data = fn(self, *args)
        except _KNOWN as e:
            log.warning("%s failed after %.2fs: %s: %s [at %s]", call, time.monotonic() - t0, type(e).__name__, e, _where(e))
            return {"ok": False, "error": str(e)}
        except Exception:
            log.exception("%s crashed after %.2fs", call, time.monotonic() - t0)  # values, not secrets: see _SECRET
            return {"ok": False, "error": "Something went wrong. Details are in app.log."}
        took = time.monotonic() - t0
        slow = name in _POLLED and took > SLOW
        level = logging.WARNING if slow else logging.DEBUG if name in _POLLED else logging.INFO
        log.log(level, "%s ok in %.2fs%s", call, took, " (slow)" if slow else "")
        return {"ok": True, "data": data}
    return wrapper


class Api:
    def __init__(self, *, admin=False, results_path=DATA_DIR / "results.json", settings_path=None):
        self._admin, self._results, self._window = admin, Path(results_path), None
        self._settings = Path(settings_path or DATA_DIR / "settings.json")  # looked up now, so tests can point DATA_DIR at tmp
        self._notify = lambda text: None  # app.py sets the tray balloon
        self._speed_lock = threading.Lock()
        self._widget, self._widget_shown, self._hid_at, self._widget_h = None, False, 0.0, 480
        self._pair_evt, self._pair_answer = threading.Event(), (False, None)
        self._main_visible = True  # app.py sets False for a --tray start and on close

    # ---- helpers (underscore: pywebview does not expose these) ----
    def _ifaces(self):
        return {wifi.adapter_key(i["description"]): i for i in wifi.interfaces()}

    def _iface(self, key):
        i = self._ifaces().get(key)
        if i is None:
            raise wifi.WifiError(f"The {wifi.ADAPTER_NAMES.get(key, key)} isn't plugged in.")
        return i

    @staticmethod
    def _name(key, fallback):
        return wifi.ADAPTER_NAMES.get(key, fallback)

    def _shape(self, iface, nets):
        saved = set(wifi.profiles().get(iface["name"], []))
        current = iface.get("ssid") if iface.get("state") == "connected" else None
        out = []
        for n in nets:
            ssid = n["ssid"]
            state = "Connected" if ssid and ssid == current else "Saved" if ssid in saved or wifi.profile_name(ssid) in saved else ""
            aps = [{"b": a["band"], "ch": a["channel"], "s": a["signal"]} for a in n["aps"] if "channel" in a and "signal" in a]
            if not aps and state == "Connected" and "channel" in iface and "signal" in iface:
                # Windows can list the connected network without access-point details until it rescans
                aps = [{"b": wifi.band(iface["channel"]), "ch": iface["channel"], "s": iface["signal"]}]
            out.append({"ssid": ssid, "sec": _SEC.get(n["auth"], n["auth"] or "?"), "auth": n["auth"], "state": state,
                        "hidden": not ssid, "aps": aps})
        out.sort(key=lambda n: (n["state"] != "Connected", -max([a["s"] for a in n["aps"]] or [0])))
        return {"networks": out, "scanned_at": time.time()}

    def _push_sample(self, phase, value):
        self._push("window.onSpeedSample && window.onSpeedSample(" + json.dumps({"phase": phase, "v": value}) + ")")

    def _push(self, script):
        for w in (self._window, self._widget):
            if w is not None:
                w.evaluate_js(script)

    def _push_step(self, text, done=False, error=False):
        self._push("window.onSwitchStep && window.onSwitchStep(" + json.dumps({"text": text, "done": done, "error": error}) + ")")

    def _follow_notify(self, text, changed):
        """The watchdog switched (or failed to switch) by itself: tell the user, and make both windows reload."""
        self._notify(text)
        if changed:
            self._push("window.onUsingChanged && window.onUsingChanged()")

    # ---- app ----
    @_envelope
    def app_info(self):
        ifs, drv = self._ifaces(), wifi.drivers()
        try:
            radios = {r["key"]: r for r in bt.radios()}
        except _KNOWN:  # Bluetooth trouble must not stop the Wi-Fi page loading
            radios = {}
        try:
            devs = hw.devices()
        except _KNOWN:  # without the device list nothing can be called off
            devs = {}
        order = ["unigen", "builtin"]
        keys = sorted({*devs, *ifs}, key=lambda k: order.index(k) if k in order else len(order))
        off = {k: bool(devs.get(k, {}).get("wifi") and devs[k]["wifi"]["disabled"]) for k in keys}
        choice = hw.load_choice(self._settings)
        using = choice if choice in keys and not off[choice] else (
            next((k for k in keys if k in ifs and ifs[k].get("state") == "connected"), None)
            or next((k for k in keys if not off[k]), None))
        return {"version": VERSION, "admin": self._admin, "using": using, "adapters": [
            {"key": k, "name": self._name(k, ifs[k]["description"] if k in ifs else k),
             "wifi": wifi.wifi_standard(drv.get(ifs[k]["name"], {}).get("radio_types", [])) if k in ifs else None,
             "bt": radios.get(k, {}).get("version"), "using": k == using, "off": off[k]} for k in keys]}

    # ---- Wi-Fi ----
    @_envelope
    def adapters(self):
        return [{"key": k, "name": self._name(k, i["description"]), "state": i["state"], "ssid": i.get("ssid"),
                 "signal": i.get("signal"), "rate": round(i["rx"]) if "rx" in i else None, "channel": i.get("channel"),
                 "band": wifi.band(i["channel"]) if "channel" in i else None} for k, i in self._ifaces().items()]

    @_envelope
    def networks(self, key):
        i = self._iface(key)
        return self._shape(i, wifi.networks(i["name"]))

    @_envelope
    def scan(self, key):
        i = self._iface(key)
        return self._shape(i, wifi.scan(i["name"], i["guid"]))

    @_envelope
    def connect(self, key, ssid, password=None):
        i = self._iface(key)
        names = wifi.profiles().get(i["name"], [])
        saved = ssid in names or wifi.profile_name(ssid) in names
        auth = None
        if not saved:
            auth = next((n["auth"] for n in wifi.networks(i["name"]) if n["ssid"] == ssid), None)
            if auth is None:
                raise wifi.WifiError(f"{ssid} is out of range.")
        st = wifi.connect(i["name"], ssid, auth=auth, password=password, saved=saved)
        return {"ssid": ssid, "rate": round(st["rx"]) if "rx" in st else None}

    @_envelope
    def disconnect(self, key):
        wifi.disconnect(self._iface(key)["name"])

    @_envelope
    def saved(self):
        by_name = {i["name"]: k for k, i in self._ifaces().items()}
        out = {}
        for iname, names in wifi.profiles().items():
            if iname in by_name:
                for n in names:
                    out.setdefault(n, []).append(by_name[iname])
        return [{"ssid": s, "on": on} for s, on in out.items()]

    @_envelope
    def password(self, ssid):
        prof = wifi.profiles()
        for i in self._ifaces().values():
            if ssid in prof.get(i["name"], []):
                return wifi.password(i["name"], ssid)
        raise wifi.WifiError(f"{ssid} isn't saved on this PC.")

    @_envelope
    def copy_profile(self, ssid, src, dst):
        wifi.copy_profile(ssid, self._iface(src)["name"], self._iface(dst)["name"])

    @_envelope
    def delete_profile(self, ssid):
        prof = wifi.profiles()
        wifi.delete_profile(ssid, [i["name"] for i in self._ifaces().values() if ssid in prof.get(i["name"], [])])
        if any(ssid in names for names in wifi.profiles().values()):  # delete_profile swallows errors: check it worked
            raise wifi.WifiError(f"Couldn't delete {ssid}.")

    # ---- Bluetooth ----
    def _eval_main(self, script):
        if self._window is not None:
            self._window.evaluate_js(script)

    def _rows(self):
        """bt.devices(); a row paired only on the other radio also names that radio and the one in use."""
        rows = bt.devices()
        if all(d.get("here", True) for d in rows):
            return rows
        rs = bt.radios()
        act = next((r for r in rs if r["ok"]), None)
        other = next((r for r in rs if r is not act), None)  # ponytail: assumes two radios; a third would need the address map
        here = self._name(act["key"], act["name"]) if act else "this radio"
        away = self._name(other["key"], other["name"]) if other else "other radio"
        for d in rows:
            if not d.get("here", True):
                d["radio_name"], d["here_name"] = away, here
        return rows

    def _row(self, dev_id):
        return next((d for d in self._rows() if dev_id in d["ids"]), None)

    def _device(self, dev_id):
        d = self._row(dev_id)
        if d is None:
            raise bt.BtError("That device isn't paired any more.")
        return d

    @_envelope
    def bt_radio(self):
        rs = bt.radios()
        return {"active": next((r["key"] for r in rs if r["ok"]), None), "can_switch": self._admin, "power": bt.power(),
                "radios": [{"key": r["key"], "name": self._name(r["key"], r["name"]), "ok": r["ok"],
                            "disabled": r["disabled"], "version": r["version"]} for r in rs]}

    @_envelope
    def bt_power(self, on):
        bt.set_power(bool(on))
        return {"power": bt.power()}

    @_envelope
    def bt_paired(self):
        return self._rows()

    def _push_nearby(self, rows, done):
        self._eval_main("window.onBtNearby && window.onBtNearby(" + json.dumps({"devices": rows, "done": done}) + ")")

    @_envelope
    def bt_search_start(self):
        bt.search_start(self._push_nearby)

    @_envelope
    def bt_search_stop(self):
        bt.search_stop()

    def _ask(self, kind, pin):
        """Runs on a pairing thread: show the prompt in the page, then wait for bt_pair_answer (not for 'display')."""
        self._pair_evt.clear()
        self._pair_answer = (False, None)
        self._eval_main("window.onPairPrompt && window.onPairPrompt(" + json.dumps({"kind": kind, "pin": pin}) + ")")
        if kind == "display":
            return True, None
        if not self._pair_evt.wait(PAIR_WAIT):
            return False, None
        return self._pair_answer

    @_envelope
    def bt_pair_answer(self, accept, pin=None):
        self._pair_answer = (bool(accept), pin if isinstance(pin, str) else None)
        self._pair_evt.set()

    @_envelope
    def bt_pair(self, dev_id):
        d = self._row(dev_id)
        # paired on the other radio only: pair it again through the radio in use
        bt.pair(bt.here_id(d["address"]) if d and not d.get("here", True) else dev_id, self._ask)
        d = self._row(dev_id)
        if d and d["kind"] in ("Headphones", "Speaker", "Audio") and not d["connected"]:
            try:  # ready to play: Windows doesn't always connect audio after pairing
                bt.connect(d["address"], d["name"], open_settings=None)
                d["connected"] = True
            except bt.BtError:
                pass  # bt logged it; the row's Connect button is still there
        return d

    @_envelope
    def bt_remove(self, dev_id):
        d = self._row(dev_id)
        bt.remove(d["ids"] if d else [dev_id])

    @_envelope
    def bt_connect(self, dev_id):
        d = self._device(dev_id)
        if not d.get("here", True):  # no audio driver on this radio: Connect can't work, Settings can't either
            raise bt.BtError(f"{d['name']} is paired with the {d['radio_name']}, not this one. Put it in pairing mode, then press Re-pair.")
        bt.connect(d["address"], d["name"])

    @_envelope
    def bt_disconnect(self, dev_id):
        d = self._device(dev_id)
        bt.disconnect(d["address"], d["name"])

    # ---- windows (private ones are called from app.py / the tray) ----
    def _show_main(self):
        self._main_visible = True
        if self._window is not None:
            self._window.show()
            self._window.restore()
            self._window.evaluate_js("window.onMainShown && window.onMainShown()")  # hidden, it stopped polling

    def _toggle_widget(self):
        if self._widget is None:
            return
        if self._widget_shown:
            self.hide_widget()
        elif time.monotonic() - self._hid_at > 0.3:  # the tray click that just blurred it should not reopen it
            self._widget_shown = True
            self._place_widget(self._widget_h)
            self._widget.show()
            self._widget.evaluate_js("window.onWidgetShown && window.onWidgetShown()")

    def _status(self):
        for a in self.adapters().get("data") or []:
            if a["state"] == "connected":
                return f"{a['name']}: {a['ssid']}, {a['signal']}%"
        return "Unigen Manager: not connected"

    @_envelope
    def open_main(self):
        self._show_main()
        if self._widget is not None:
            self.hide_widget()

    @_envelope
    def hide_widget(self):
        if self._widget is not None:
            self._widget.hide()
        self._widget_shown, self._hid_at = False, time.monotonic()

    @_envelope
    def is_visible(self, which):
        """Hidden windows stop polling: the pages ask before each refresh."""
        return self._main_visible if which == "main" else self._widget_shown

    def _place_widget(self, h):
        x, y = tray.widget_position(tray.work_area(), tray.WIDGET_W, h, tray.scale())
        self._widget.resize(tray.WIDGET_W, h)
        self._widget.move(x, y)

    @_envelope
    def widget_fit(self, height):
        """The widget page reports its height; keep its bottom-right corner just above the taskbar."""
        if self._widget is None:
            return
        self._widget_h = int(max(200, min(900, round(height))))
        self._place_widget(self._widget_h)

    @_envelope
    def switch_to(self, key):
        """Make this adapter the one in use, Wi-Fi and Bluetooth together. Every step is pushed to both windows."""
        if not self._admin:
            raise hw.HwError("Switching adapters needs administrator rights. Restart the app and choose Yes.")
        last = []

        def step(text):
            last[:] = [text]
            self._push_step(text)
        try:
            hw.use(key, on_step=step, path=self._settings,  # Bluetooth finishes after this returns
                   on_later=lambda text, ok: self._push_step(text, done=True, error=not ok))
        except hw.HwError as e:
            self._push_step(str(e), done=True, error=True)
            raise
        self._push_step(last[0] if last else "", done=True)
        return {"using": key}

    # ---- speed ----
    @_envelope
    def speed_test(self, key):
        if not self._speed_lock.acquire(blocking=False):
            raise speed.SpeedError("A speed test is already running.")
        try:
            i = self._iface(key)
            addr = speed.addresses(i["name"])
            result = speed.run_test(addr["ip"], addr["gateway"], on_sample=self._push_sample)
            result["link"] = round(i["rx"]) if "rx" in i else None
            speed.save_result(self._results, key, result)
            return result
        finally:
            self._speed_lock.release()

    @_envelope
    def speed_results(self):
        return speed.load_results(self._results)
