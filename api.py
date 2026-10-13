"""What the page calls (window.pywebview.api). Every public method returns {"ok", "data"} or {"ok", "error"}.
pywebview runs each call on its own thread, so slow work never blocks the window."""
import functools, json, logging, os, threading, time
from pathlib import Path

import bt, speed, tray, wifi, winrun

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "UnigenManager"
log = logging.getLogger("unigen")
_KNOWN = (wifi.WifiError, wifi.ParseError, bt.BtError, speed.SpeedError, winrun.CmdError)
_SEC = {"WPA2-Personal": "WPA2", "WPA3-Personal": "WPA3", "Open": "Open", "WPA-Personal": "WPA", "WPA2-Enterprise": "WPA2-Ent"}


def _envelope(fn):
    @functools.wraps(fn)
    def wrapper(self, *args):
        try:
            return {"ok": True, "data": fn(self, *args)}
        except _KNOWN as e:
            return {"ok": False, "error": str(e)}
        except Exception:
            log.exception("%s failed", fn.__name__)  # traceback only: argument values (passwords) are never logged
            return {"ok": False, "error": "Something went wrong. Details are in app.log."}
    return wrapper


class Api:
    def __init__(self, *, admin=False, results_path=DATA_DIR / "results.json"):
        self._admin, self._results, self._window = admin, Path(results_path), None
        self._speed_lock = threading.Lock()
        self._widget, self._widget_shown, self._hid_at, self._widget_h = None, False, 0.0, 480
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
            out.append({"ssid": ssid, "sec": _SEC.get(n["auth"], n["auth"] or "?"), "auth": n["auth"], "state": state,
                        "hidden": not ssid, "aps": [{"b": a["band"], "ch": a["channel"], "s": a["signal"]}
                                                    for a in n["aps"] if "channel" in a and "signal" in a]})
        out.sort(key=lambda n: (n["state"] != "Connected", -max([a["s"] for a in n["aps"]] or [0])))
        return {"networks": out, "scanned_at": time.time()}

    def _device(self, dev_id):
        d = next((d for d in bt.devices(paired=True) if d["id"] == dev_id), None)
        if d is None:
            raise bt.BtError("That device isn't paired any more.")
        return d

    def _push_sample(self, phase, value):
        script = "window.onSpeedSample && window.onSpeedSample(" + json.dumps({"phase": phase, "v": value}) + ")"
        for w in (self._window, self._widget):
            if w is not None:
                w.evaluate_js(script)

    # ---- app ----
    @_envelope
    def app_info(self):
        ifs, drv = self._ifaces(), wifi.drivers()
        try:
            radios = {r["key"]: r for r in bt.radios()}
        except _KNOWN:  # Bluetooth trouble must not stop the Wi-Fi page loading
            radios = {}
        return {"admin": self._admin, "adapters": [
            {"key": k, "name": self._name(k, i["description"]),
             "wifi": wifi.wifi_standard(drv.get(i["name"], {}).get("radio_types", [])),
             "bt": radios.get(k, {}).get("version")} for k, i in ifs.items()]}

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
    @_envelope
    def bt_radio(self):
        rs = bt.radios()
        return {"active": next((r["key"] for r in rs if r["ok"]), None), "can_switch": self._admin,
                "radios": [{"key": r["key"], "name": self._name(r["key"], r["name"]), "ok": r["ok"],
                            "disabled": r["disabled"], "version": r["version"]} for r in rs]}

    @_envelope
    def bt_switch(self, key):
        if not self._admin:
            raise bt.BtError("Bluetooth radio switching needs administrator rights. Restart the app and choose Yes.")
        return {"active": bt.switch(key)}

    @_envelope
    def bt_paired(self):
        return bt.devices(paired=True)

    @_envelope
    def bt_nearby(self):
        return bt.devices(paired=False)

    @_envelope
    def bt_pair(self, dev_id):
        bt.pair(dev_id)

    @_envelope
    def bt_remove(self, dev_id):
        bt.remove(dev_id)

    @_envelope
    def bt_connect(self, dev_id):
        d = self._device(dev_id)
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
    def use_adapter(self, key):
        """Wi-Fi uses this adapter: it joins the network the other one is on, then the other disconnects."""
        ifs = self._ifaces()
        target = self._iface(key)
        others = [i for k, i in ifs.items() if k != key]
        if target.get("state") == "connected":
            net = target.get("ssid")
        else:
            net = next((o.get("ssid") for o in others if o.get("state") == "connected"), None)
        if not net:
            raise wifi.WifiError("Neither adapter is connected. Connect to a network first.")
        if not (target.get("state") == "connected" and target.get("ssid") == net):
            names = wifi.profiles().get(target["name"], [])
            if net not in names and wifi.profile_name(net) not in names:  # reuse the other adapter's saved password
                src = next(o for o in others if o.get("ssid") == net)
                wifi.copy_profile(src.get("profile") or net, src["name"], target["name"])
            wifi.connect(target["name"], net, saved=True)
        for o in others:
            if o.get("state") == "connected":
                wifi.disconnect(o["name"])
        return {"key": key, "ssid": net}

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
