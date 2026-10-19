"""The dongle's Wi-Fi driver, installed from inside the app. Only on the user's click (api.install_driver), never on startup.

The source is pinned twice: the URL names one commit of a community mirror of the vendor's installers, and the file must
hash to SHA256. The vendor's installer is never run: innoextract (bundled, tools/innoextract) unpacks the signed driver
files from it, and Windows' own pnputil installs them. Nothing is installed unless the hash, the catalog signatures and
the hardware id all check out."""
import hashlib, logging, platform, shutil, tempfile, threading, time, urllib.request
from pathlib import Path

import pnp, winrun

log = logging.getLogger("unigen")
ROOT = Path(__file__).resolve().parent
EXTRACTOR = ROOT / "tools" / "innoextract" / "innoextract.exe"

# community mirror of the AIC installers (no licence of its own), pinned to one commit; AIC's installer is Authenticode-signed
URL = ("https://raw.githubusercontent.com/peckishrine/aic8800_windows_drivers/d95fedce4c3ecf0a9d43fc5a899631880231c460/"
       "drivers/Latest_Driver_AX900_USB_WiFi_6_and_Bluetooth_Adapter.exe")
SHA256 = "151e305aa1231085ad225638b03fd53c6c1b05f69f5a042db4f826ae794970a4"
SIZE = 3_322_984
MAX_BYTES = 16_000_000   # a longer stream than this is not the file (SIZE is 3.3 MB): stop reading
INNER = "app\\win10_x64"  # inside the installer: the Windows 10/11 64-bit driver packages
INF_FW, INF_WIFI = "aicloadfw.inf", "aicusbwifi.inf"  # firmware loader first, then the Wi-Fi function
WIFI_ID = "USB\\VID_368B&PID_8D81&MI_02"  # the dongle's Wi-Fi function
LOADER_IDS = ("USB\\VID_A69C&PID_8D80", "USB\\VID_A69C&PID_8800")  # the dongle before its firmware is loaded
NO_DRIVER = (1, 28)      # CM_PROB_NOT_CONFIGURED, CM_PROB_FAILED_INSTALL: Windows has no driver for the device
PNPUTIL_OK = (0, 259, 3010)  # 259: staged, no device matched it (yet); 3010: installed, a restart finishes it
CONNECT_TIMEOUT = 30     # s: no answer from the server for this long ends the download
DOWNLOAD_CHUNK = 64 * 1024
PROGRESS_EVERY = 0.25    # s between "1.2 of 3.3 MB" updates
LOADER_WAIT = 25.0       # s the dongle may take, after its firmware loads, to show up as the Wi-Fi function
START_WAIT = 30.0        # s the Wi-Fi function may take to start after its driver is installed
EXTRACT_TIMEOUT = 60
INSTALL_TIMEOUT = 120    # s per pnputil call
STEPS = 5
LABELS = ("Downloading", "Verifying", "Unpacking", "Installing", "Checking")


class DriverError(Exception):
    """The install could not finish; str(e) is safe to show the user and says what state the PC is in."""


class Busy(DriverError):
    """An install is already running (its bar must stay)."""


_lock = threading.Lock()


def nodes():
    """The present USB devices that are the dongle (Wi-Fi function, Bluetooth, or the firmware-loader stage)."""
    return pnp.present_nodes("USB", ("USB\\VID_368B&PID_8D81", "USB\\VID_A69C"))


def plan(scan=nodes):
    """{"state": "installed" | "missing" | "absent", "loader": bool}. missing: the dongle is plugged in and Windows has no
    Wi-Fi driver for it (its Wi-Fi function shows code 28, or it is still the firmware-loader device); absent: no dongle."""
    found = scan()
    wifi = [n for n in found if n["id"].upper().startswith(WIFI_ID)]
    loader = [n for n in found if n["id"].upper().startswith(LOADER_IDS)]
    if wifi and not all(n["problem"] in NO_DRIVER for n in wifi):
        return {"state": "installed", "loader": False}
    return {"state": "missing" if wifi or loader else "absent", "loader": bool(loader)}


def _mb(n):
    return f"{n / 1e6:.1f}"


def download(dest, on_progress=lambda done, total: None, cancel=None, *, opener=urllib.request.urlopen, clock=time.monotonic):
    """Stream URL into dest. Raises DriverError on a network failure, a cancel, or an over-long stream."""
    req = urllib.request.Request(URL, headers={"User-Agent": "UnigenManager"})
    try:
        with opener(req, timeout=CONNECT_TIMEOUT) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or SIZE)
            done, last = 0, 0.0
            while chunk := r.read(DOWNLOAD_CHUNK):
                if cancel is not None and cancel.is_set():
                    raise DriverError("Cancelled. Nothing was installed.")
                done += len(chunk)
                if done > MAX_BYTES:
                    raise DriverError("The download was far bigger than expected, so it was stopped. Nothing was installed.")
                f.write(chunk)
                if clock() - last >= PROGRESS_EVERY:
                    last = clock()
                    on_progress(done, total)
            on_progress(done, total)
    except DriverError:
        raise
    except OSError as e:  # URLError, timeouts and disk errors are all OSError
        raise DriverError(f"Couldn't download the driver ({getattr(e, 'reason', None) or e}). Check the internet connection. Nothing was installed.") from None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def verify(path):
    """The file must be exactly the pinned installer."""
    if sha256(path) != SHA256:
        raise DriverError("The downloaded file isn't the expected driver (its checksum differs), so it was not used. Nothing was installed.")


def _text(path):
    b = Path(path).read_bytes()
    return b.decode("utf-16") if b[:2] in (b"\xff\xfe", b"\xfe\xff") else b.decode("latin-1")


def extract(exe, out, *, extractor=None):
    """Unpack the win10 x64 driver files from the installer WITHOUT running it. Returns {"fw": inf Path, "wifi": inf Path}."""
    tool = Path(extractor or EXTRACTOR)
    if not tool.is_file():
        raise DriverError("The driver unpacker is missing from this copy of the app. Nothing was installed.")
    winrun.run([str(tool), "-q", "-d", str(out), "-I", INNER, str(exe)], timeout=EXTRACT_TIMEOUT)
    pkg = next((p for p in Path(out).rglob("*") if p.is_dir() and p.name.lower() == "win10_x64"), None)
    files = {p.name.lower(): p for p in pkg.iterdir() if p.is_file()} if pkg else {}
    need = [n for stem in ("aicloadfw", "aicusbwifi") for n in (f"{stem}.inf", f"{stem}.cat", f"{stem}.sys")]
    if missing := [n for n in need if n not in files]:
        raise DriverError(f"The driver package is missing {', '.join(missing)}. Nothing was installed.")
    return {"fw": files[INF_FW], "wifi": files[INF_WIFI]}


def check_signed(infs):
    """Every catalog must carry a valid signature (Windows checks again when it installs), and the Wi-Fi INF must list the dongle."""
    cats = [str(p.with_suffix(".cat")) for p in infs.values()]
    # PSModulePath is reset first: a PowerShell 7 parent leaves its module folders in it, and 5.1 then can't load the Security module
    out = winrun.ps('$env:PSModulePath = "$PSHOME\\Modules"\n'
                    '$p.cats | ForEach-Object { (Get-AuthenticodeSignature -LiteralPath $_).Status.ToString() }', {"cats": cats})
    if [s.strip() for s in out.splitlines() if s.strip()] != ["Valid"] * len(cats):
        raise DriverError("The driver's signature isn't valid, so it was not installed.")
    if WIFI_ID.upper() not in _text(infs["wifi"]).upper():
        raise DriverError("That driver package doesn't list this dongle, so it was not installed.")


def pnputil(inf):
    winrun.run(["pnputil.exe", "/add-driver", str(inf), "/install"], timeout=INSTALL_TIMEOUT, ok_codes=PNPUTIL_OK)


def _wait(done, wait, sleep, clock):
    deadline = clock() + wait
    while not done():
        if clock() >= deadline:
            return False
        sleep(0.5)
    return True


def install(on_step, on_progress=lambda text, label: None, cancel=None, *, scan=nodes, sleep=time.sleep, clock=time.monotonic,
            download=download, extractor=None):
    """Download, verify, unpack, install, check. on_step(text, step, of, label) starts each step (api.Mover.step);
    on_progress(text, label) refreshes the download's line. Cancel (a threading.Event) works until the install step starts.
    Raises DriverError; the temp files are always removed, and no step before "Installing" changes Windows."""
    if not _lock.acquire(blocking=False):
        raise Busy("The driver is already being installed.")
    def stop():
        if cancel is not None and cancel.is_set():
            raise DriverError("Cancelled. Nothing was installed.")
    tmp = Path(tempfile.mkdtemp(prefix="unigen-driver-"))
    try:
        if platform.machine().upper() not in ("AMD64", "X86_64"):
            raise DriverError("This driver is for 64-bit Windows on Intel or AMD.")
        before = plan(scan)
        if before["state"] != "missing":
            raise DriverError("The dongle isn't plugged in." if before["state"] == "absent" else "The dongle already has its Wi-Fi driver.")
        exe = tmp / "driver.exe"
        on_step("Downloading the driver…", 1, STEPS, LABELS[0])
        download(exe, lambda done, total: on_progress(f"Downloading the driver… {_mb(done)} of {_mb(total)} MB",
                                                      f"{LABELS[0]} {_mb(done)} of {_mb(total)} MB"), cancel)
        stop()
        on_step("Checking the download…", 2, STEPS, LABELS[1])
        verify(exe)
        stop()
        on_step("Unpacking the driver…", 3, STEPS, LABELS[2])
        infs = extract(exe, tmp / "out", extractor=extractor)
        check_signed(infs)
        stop()
        on_step("Installing the driver…", 4, STEPS, LABELS[3])  # from here on nothing is cancelled half-way
        log.info("driver: installing %s then %s", INF_FW, INF_WIFI)
        pnputil(infs["fw"])
        if before["loader"]:  # the dongle reloads with its firmware and shows up again as itself
            _wait(lambda: any(n["id"].upper().startswith(WIFI_ID) for n in scan()), LOADER_WAIT, sleep, clock)
        pnputil(infs["wifi"])
        on_step("Starting the dongle's Wi-Fi…", 5, STEPS, LABELS[4])
        if not _wait(lambda: any(n["started"] for n in scan() if n["id"].upper().startswith(WIFI_ID)), START_WAIT, sleep, clock):
            raise DriverError("The driver is installed, but the dongle's Wi-Fi hasn't started. Unplug the dongle and plug it back in.")
    except winrun.CmdError as e:
        raise DriverError(f"Windows couldn't install the driver: {e}") from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        _lock.release()

