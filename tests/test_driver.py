import hashlib, io, json, os, threading
from pathlib import Path

import pytest

import api, driver, hw as hwm, winrun

WIFI = r"USB\VID_368B&PID_8D81&MI_02\6&28B24B5D&0&0002"
LOADER = r"USB\VID_A69C&PID_8D80\5&1&0&2"
BT = r"USB\VID_368B&PID_8D81&MI_00\6&28B24B5D&0&0000"


def node(i, started=True, problem=0):
    return {"id": i, "started": started and not problem, "problem": problem}


# ---- plan: is the dongle here, and does Windows have its Wi-Fi driver? ----
def test_plan_installed_missing_absent():
    assert driver.plan(lambda: [node(WIFI)]) == {"state": "installed", "loader": False}
    assert driver.plan(lambda: [node(BT, problem=22), node(WIFI)])["state"] == "installed"  # Bluetooth off by choice says nothing
    assert driver.plan(lambda: [node(WIFI, problem=22)])["state"] == "installed"  # switched off in Device Manager: it has a driver
    assert driver.plan(lambda: [node(WIFI, problem=28)]) == {"state": "missing", "loader": False}  # code 28: no driver
    assert driver.plan(lambda: [node(BT, problem=28), node(WIFI, problem=28)])["state"] == "missing"
    assert driver.plan(lambda: [node(LOADER, problem=28)]) == {"state": "missing", "loader": True}  # fresh PC: firmware not loaded yet
    assert driver.plan(lambda: []) == {"state": "absent", "loader": False}
    assert driver.plan(lambda: [node(BT)])["state"] == "absent"  # a Bluetooth node alone is not the Wi-Fi function


# ---- download ----
class Resp(io.BytesIO):
    def __init__(self, data, length=None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if length is None else length)}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_download_streams_with_progress(tmp_path):
    seen, dest = [], tmp_path / "f"
    driver.download(dest, lambda d, t: seen.append((d, t)), opener=lambda req, timeout: Resp(b"x" * 200_000), clock=iter(range(0, 99, 1)).__next__)
    assert dest.read_bytes() == b"x" * 200_000
    assert seen[-1] == (200_000, 200_000) and seen[0][0] <= seen[-1][0]


def test_download_asks_the_pinned_url():
    got = {}

    def opener(req, timeout):
        got["url"], got["timeout"] = req.full_url, timeout
        return Resp(b"")
    driver.download(Path(os.devnull), opener=opener)
    assert got == {"url": driver.URL, "timeout": driver.CONNECT_TIMEOUT}
    assert "d95fedce4c3ecf0a9d43fc5a899631880231c460" in driver.URL


def test_download_cancel_overlong_and_network_errors(tmp_path):
    ev = threading.Event()
    ev.set()
    with pytest.raises(driver.DriverError, match="Cancelled"):
        driver.download(tmp_path / "f", cancel=ev, opener=lambda r, timeout: Resp(b"x" * 10))
    with pytest.raises(driver.DriverError, match="far bigger"):
        driver.download(tmp_path / "f", opener=lambda r, timeout: Resp(b"x" * (driver.MAX_BYTES + 1)))

    def down(req, timeout):
        raise OSError("getaddrinfo failed")
    with pytest.raises(driver.DriverError, match="internet connection"):
        driver.download(tmp_path / "f", opener=down)


# ---- the hash pin ----
def test_verify_passes_only_the_pinned_hash(tmp_path, monkeypatch):
    f = tmp_path / "d.exe"
    f.write_bytes(b"the driver")
    monkeypatch.setattr(driver, "SHA256", hashlib.sha256(b"the driver").hexdigest())
    driver.verify(f)
    f.write_bytes(b"the driver!")
    with pytest.raises(driver.DriverError, match="checksum differs"):
        driver.verify(f)


def test_the_pin_is_the_users_chosen_file():
    assert driver.SHA256 == "151e305aa1231085ad225638b03fd53c6c1b05f69f5a042db4f826ae794970a4" and driver.SIZE == 3_322_984
    assert driver.URL.endswith("/Latest_Driver_AX900_USB_WiFi_6_and_Bluetooth_Adapter.exe")


# ---- extract: the vendor installer is unpacked, never run ----
def fake_unpack(names, calls):
    def run(args, **kw):
        calls.append(args)
        out = Path(args[args.index("-d") + 1]) / "app" / "win10_x64"
        out.mkdir(parents=True)
        for n in names:
            (out / n).write_text("x")
    return run


ALL = ["aicloadfw.Inf", "aicloadfw.Sys", "aicloadfw.cat", "aicusbwifi.Inf", "aicusbwifi.Sys", "aicusbwifi.cat", "DPInst64.exe"]


def test_extract_unpacks_with_the_bundled_tool_and_finds_both_infs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(winrun, "run", fake_unpack(ALL, calls))
    tool = tmp_path / "innoextract.exe"
    tool.write_text("")
    infs = driver.extract(tmp_path / "d.exe", tmp_path / "out", extractor=tool)
    assert infs["fw"].name == "aicloadfw.Inf" and infs["wifi"].name == "aicusbwifi.Inf"  # found whatever the case
    assert calls == [[str(tool), "-q", "-d", str(tmp_path / "out"), "-I", "app\\win10_x64", str(tmp_path / "d.exe")]]
    assert driver.EXTRACTOR.is_file()  # shipped with the app


def test_extract_refuses_an_incomplete_package_or_a_missing_tool(tmp_path, monkeypatch):
    tool = tmp_path / "innoextract.exe"
    tool.write_text("")
    monkeypatch.setattr(winrun, "run", fake_unpack([n for n in ALL if n != "aicusbwifi.cat"], []))
    with pytest.raises(driver.DriverError, match="missing aicusbwifi.cat"):
        driver.extract(tmp_path / "d.exe", tmp_path / "out", extractor=tool)
    with pytest.raises(driver.DriverError, match="unpacker is missing"):
        driver.extract(tmp_path / "d.exe", tmp_path / "o2", extractor=tmp_path / "nope.exe")


@pytest.mark.skipif(not os.environ.get("UNIGEN_DRIVER_EXE"), reason="set UNIGEN_DRIVER_EXE to the downloaded installer to run the real unpacker")
def test_real_extract_check_and_hash(tmp_path):
    exe = Path(os.environ["UNIGEN_DRIVER_EXE"])
    driver.verify(exe)
    infs = driver.extract(exe, tmp_path / "out")
    driver.check_signed(infs)  # WHQL catalogs, and the INF lists the dongle
    assert not list((tmp_path / "out").rglob("AicWifiService.exe"))  # only the driver folder is unpacked


# ---- signature and hardware id ----
def infs_in(tmp_path, wifi_text=f"x = a, {driver.WIFI_ID}"):
    fw, wifi = tmp_path / "aicloadfw.inf", tmp_path / "aicusbwifi.inf"
    fw.write_bytes("[Version]\n".encode("utf-16"))  # the loader INF ships as UTF-16
    wifi.write_text(wifi_text)
    return {"fw": fw, "wifi": wifi}


def test_check_signed_needs_valid_catalogs_and_the_dongles_id(tmp_path, monkeypatch):
    seen = {}

    def ps(script, params=None, **kw):
        seen.update(params)
        return "Valid\r\nValid\r\n"
    monkeypatch.setattr(winrun, "ps", ps)
    driver.check_signed(infs_in(tmp_path))
    assert seen["cats"] == [str(tmp_path / "aicloadfw.cat"), str(tmp_path / "aicusbwifi.cat")]
    monkeypatch.setattr(winrun, "ps", lambda *a, **k: "Valid\nHashMismatch\n")
    with pytest.raises(driver.DriverError, match="signature isn't valid"):
        driver.check_signed(infs_in(tmp_path))
    monkeypatch.setattr(winrun, "ps", lambda *a, **k: "")
    with pytest.raises(driver.DriverError, match="signature isn't valid"):
        driver.check_signed(infs_in(tmp_path))
    monkeypatch.setattr(winrun, "ps", lambda *a, **k: "Valid\nValid\n")
    with pytest.raises(driver.DriverError, match="doesn't list this dongle"):
        driver.check_signed(infs_in(tmp_path, "x = a, USB\\VID_A69C&PID_8D81&MI_02"))
    driver.check_signed(infs_in(tmp_path, f"x = a, {driver.WIFI_ID.lower()}"))  # the INF's own case differs


# ---- install: the whole flow with Windows mocked ----
class Rig:
    """Mocks download/verify/extract/sign-check/pnputil/PnP and records what the flow did, in order."""

    def __init__(self, monkeypatch, tmp_path, *, nodes=None, hash_ok=True, signed=True):
        self.log, self.steps, self.progress, self.tmp, self.temps = [], [], [], tmp_path, []
        self.nodes = nodes if nodes is not None else [node(WIFI, problem=28)]
        monkeypatch.setattr(driver.tempfile, "mkdtemp", self.mkdtemp)
        monkeypatch.setattr(driver, "verify", lambda p: self.log.append("verify") or (None if hash_ok else self.bad()))
        monkeypatch.setattr(driver, "extract", self.extract)
        monkeypatch.setattr(driver, "check_signed", lambda infs: self.log.append("signed") or (None if signed else self.bad("sig")))
        monkeypatch.setattr(driver, "pnputil", lambda inf: (self.log.append(f"pnputil {Path(inf).name}"), self.after_pnputil(Path(inf).name)))
        monkeypatch.setattr(driver.platform, "machine", lambda: "AMD64")
        self.scan = lambda: list(self.nodes)

    def bad(self, what="hash"):
        raise driver.DriverError(f"bad {what}")

    def mkdtemp(self, prefix):
        d = self.tmp / f"t{len(self.temps)}"
        d.mkdir()
        self.temps.append(d)
        return str(d)

    def download(self, dest, on_progress, cancel):
        self.log.append("download")
        Path(dest).write_bytes(b"exe")
        on_progress(1_000_000, 3_322_984)

    def extract(self, exe, out, **kw):
        self.log.append("extract")
        assert Path(exe).exists()
        return {"fw": Path(out) / "aicloadfw.inf", "wifi": Path(out) / "aicusbwifi.inf"}

    def after_pnputil(self, name):
        if name == "aicusbwifi.inf":  # Windows binds the driver: the Wi-Fi function starts
            self.nodes = [node(WIFI)]

    def run(self, cancel=None):
        driver.install(lambda text, step, of, label: self.steps.append((text, step, of, label)),
                       lambda text, label: self.progress.append((text, label)), cancel,
                       scan=lambda: self.scan(), sleep=lambda s: None, clock=iter(range(0, 10_000)).__next__, download=self.download)


def test_install_runs_the_steps_in_order_and_cleans_up(monkeypatch, tmp_path):
    r = Rig(monkeypatch, tmp_path)
    r.run()
    assert r.log == ["download", "verify", "extract", "signed", "pnputil aicloadfw.inf", "pnputil aicusbwifi.inf"]  # firmware loader first
    assert [(s[1], s[2], s[3]) for s in r.steps] == [(1, 5, "Downloading"), (2, 5, "Verifying"), (3, 5, "Unpacking"), (4, 5, "Installing"), (5, 5, "Checking")]
    assert r.progress == [("Downloading the driver… 1.0 of 3.3 MB", "Downloading 1.0 of 3.3 MB")]
    assert not r.temps[0].exists()  # temp dir removed
    assert not driver._lock.locked()


def test_pnputil_is_called_with_add_driver_and_install(monkeypatch):
    calls = []
    monkeypatch.setattr(winrun, "run", lambda args, **kw: calls.append((args, kw)))
    driver.pnputil(Path("C:/x/aicloadfw.inf"))
    assert calls == [(["pnputil.exe", "/add-driver", str(Path("C:/x/aicloadfw.inf")), "/install"],
                      {"timeout": driver.INSTALL_TIMEOUT, "ok_codes": (0, 259, 3010)})]


def test_a_wrong_hash_stops_before_anything_is_unpacked_or_installed(monkeypatch, tmp_path):
    r = Rig(monkeypatch, tmp_path, hash_ok=False)
    with pytest.raises(driver.DriverError, match="bad hash"):
        r.run()
    assert r.log == ["download", "verify"] and not r.temps[0].exists()


def test_a_bad_signature_stops_before_pnputil(monkeypatch, tmp_path):
    r = Rig(monkeypatch, tmp_path, signed=False)
    with pytest.raises(driver.DriverError, match="bad sig"):
        r.run()
    assert "pnputil aicloadfw.inf" not in r.log and not r.temps[0].exists()


def test_cancel_works_until_the_install_step(monkeypatch, tmp_path):
    ev = threading.Event()
    r = Rig(monkeypatch, tmp_path)
    r.download = lambda dest, on_progress, cancel: ev.set()  # the user pressed Cancel while it downloaded
    with pytest.raises(driver.DriverError, match="Cancelled. Nothing was installed"):
        r.run(ev)
    assert r.log == [] and [s[1] for s in r.steps] == [1] and not r.temps[0].exists()
    ev2 = threading.Event()  # Cancel pressed once Windows is installing: it finishes
    r2 = Rig(monkeypatch, tmp_path)
    r2.after_pnputil = lambda name: (ev2.set(), Rig.after_pnputil(r2, name))
    r2.run(ev2)
    assert r2.log[-1] == "pnputil aicusbwifi.inf"


def test_a_pnputil_failure_is_reported_in_plain_words(monkeypatch, tmp_path):
    r = Rig(monkeypatch, tmp_path)

    def boom(inf):
        raise winrun.CmdError("The third-party INF does not contain digital signature information.")
    monkeypatch.setattr(driver, "pnputil", boom)
    with pytest.raises(driver.DriverError, match="Windows couldn't install the driver: The third-party INF"):
        r.run()
    assert not r.temps[0].exists()


def test_install_refuses_when_there_is_nothing_to_install(monkeypatch, tmp_path):
    with pytest.raises(driver.DriverError, match="isn't plugged in"):
        Rig(monkeypatch, tmp_path, nodes=[]).run()
    r = Rig(monkeypatch, tmp_path, nodes=[node(WIFI)])
    with pytest.raises(driver.DriverError, match="already has"):
        r.run()
    assert r.log == []  # nothing downloaded
    arm = Rig(monkeypatch, tmp_path)
    monkeypatch.setattr(driver.platform, "machine", lambda: "ARM64")
    with pytest.raises(driver.DriverError, match="64-bit"):
        arm.run()


def test_a_firmware_loader_dongle_waits_for_the_wifi_function_between_the_two_installs(monkeypatch, tmp_path):
    r = Rig(monkeypatch, tmp_path, nodes=[node(LOADER, problem=28)])
    reads = []

    def scan():
        reads.append(1)
        if "pnputil aicloadfw.inf" in r.log and "pnputil aicusbwifi.inf" not in r.log:
            return [node(WIFI, problem=28)] if len(reads) > 3 else [node(LOADER)]  # it re-enumerates a moment after the firmware loads
        return list(r.nodes)
    r.scan = scan
    r.run()
    assert r.log[-2:] == ["pnputil aicloadfw.inf", "pnputil aicusbwifi.inf"] and len(reads) > 3


def test_the_wifi_function_that_never_starts_is_an_error_that_says_what_to_do(monkeypatch, tmp_path):
    r = Rig(monkeypatch, tmp_path)
    r.after_pnputil = lambda name: None
    with pytest.raises(driver.DriverError, match="Unplug the dongle and plug it back in"):
        r.run()


def test_a_second_install_is_refused_while_one_runs(monkeypatch, tmp_path):
    r = Rig(monkeypatch, tmp_path)
    inner = []
    real = r.download

    def download(dest, on_progress, cancel):
        try:
            r.run()
        except driver.Busy as e:
            inner.append(e)
        real(dest, on_progress, cancel)
    r.download = download
    r.run()
    assert len(inner) == 1 and r.log[-1] == "pnputil aicusbwifi.inf"


# ---- api: the steps both windows get ----
class Win:
    def __init__(self):
        self.scripts = []

    def evaluate_js(self, s):
        self.scripts.append(s)


def pushed(w):
    return [json.loads(s.split("onSwitchStep(", 1)[1][:-1]) for s in w.scripts]


@pytest.fixture
def quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)


def test_driver_status(monkeypatch, quiet):
    monkeypatch.setattr(driver, "plan", lambda: {"state": "missing", "loader": False})
    assert api.Api(admin=True).driver_status() == {"ok": True, "data": {"state": "missing", "loader": False, "can_install": True}}
    assert api.Api(admin=False).driver_status()["data"]["can_install"] is False


def test_install_driver_pushes_every_step_to_both_windows(monkeypatch, quiet):
    def fake(on_step, on_progress, cancel):
        on_step("Downloading the driver…", 1, 5, "Downloading")
        on_progress("Downloading the driver… 1.0 of 3.3 MB", "Downloading 1.0 of 3.3 MB")
        on_step("Checking the download…", 2, 5, "Verifying")
    monkeypatch.setattr(driver, "install", fake)
    monkeypatch.setattr(driver, "plan", lambda: {"state": "installed", "loader": False})
    a = api.Api(admin=True)
    a._window, a._widget = Win(), Win()
    assert a.install_driver() == {"ok": True, "data": {"state": "installed", "loader": False}}
    for w in (a._window, a._widget):
        assert pushed(w) == [
            {"kind": "driver", "text": "Downloading the driver…", "done": False, "error": False, "step": 1, "of": 5, "label": "Downloading"},
            {"kind": "driver", "text": "Downloading the driver… 1.0 of 3.3 MB", "done": False, "error": False, "step": 1, "of": 5, "label": "Downloading 1.0 of 3.3 MB"},
            {"kind": "driver", "text": "Checking the download…", "done": False, "error": False, "step": 2, "of": 5, "label": "Verifying"},
            {"kind": "driver", "text": "Driver installed. The dongle's Wi-Fi is ready.", "done": True, "error": False, "step": 2, "of": 5, "label": "Verifying"}]


def test_a_failed_install_driver_names_the_step_it_stopped_at(monkeypatch, quiet):
    def fake(on_step, on_progress, cancel):
        on_step("Checking the download…", 2, 5, "Verifying")
        raise driver.DriverError("The downloaded file isn't the expected driver (its checksum differs), so it was not used. Nothing was installed.")
    monkeypatch.setattr(driver, "install", fake)
    a = api.Api(admin=True)
    a._window = Win()
    r = a.install_driver()
    assert r["ok"] is False and "checksum differs" in r["error"]
    assert pushed(a._window)[-1] == {"kind": "driver", "text": r["error"], "done": True, "error": True, "step": 2, "of": 5, "label": "Verifying"}


def test_install_driver_needs_admin_and_a_busy_one_doesnt_end_the_running_bar(monkeypatch, quiet):
    monkeypatch.setattr(driver, "install", lambda *a, **k: pytest.fail("must not install without admin"))
    a = api.Api(admin=False)
    a._window = Win()
    assert a.install_driver() == {"ok": False, "error": "Installing the driver needs administrator rights. Restart the app and choose Yes."}

    def busy(*a, **k):
        raise driver.Busy("The driver is already being installed.")
    monkeypatch.setattr(driver, "install", busy)
    b = api.Api(admin=True)
    b._window = Win()
    assert b.install_driver()["error"] == "The driver is already being installed."
    assert pushed(b._window) == []


def test_cancel_driver_sets_the_event_the_install_got(monkeypatch, quiet):
    got = []
    monkeypatch.setattr(driver, "install", lambda on_step, on_progress, cancel: got.append(cancel))
    monkeypatch.setattr(driver, "plan", lambda: {"state": "installed", "loader": False})
    a = api.Api(admin=True)
    a.install_driver()
    assert not got[0].is_set() and a.cancel_driver()["ok"] and got[0].is_set()


def test_app_info_calls_a_dongle_without_a_driver_no_driver(monkeypatch, quiet):
    monkeypatch.setattr(hwm, "devices", lambda: {})
    monkeypatch.setattr(api.wifi, "interfaces", lambda: [])
    monkeypatch.setattr(api.wifi, "drivers", lambda: {})
    monkeypatch.setattr(api.bt, "radios", lambda: [])
    monkeypatch.setattr(driver, "plan", lambda: {"state": "missing", "loader": False})
    assert api.Api(admin=True).app_info()["data"]["dongle"] == "no_driver"
    monkeypatch.setattr(driver, "plan", lambda: {"state": "absent", "loader": False})
    assert api.Api(admin=True).app_info()["data"]["dongle"] == "unplugged"
