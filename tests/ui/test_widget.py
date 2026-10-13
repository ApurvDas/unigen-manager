"""Widget UI tests: ui/widget.html?mock with its fake taskbar, in the installed Microsoft Edge."""
import functools, http.server, threading
from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.ui
UI = Path(__file__).resolve().parents[2] / "ui"


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def base_url():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(UI)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/widget.html?mock"
    httpd.shutdown()



@pytest.fixture
def widget(browser, base_url):
    pages = []

    def _open(hooks=""):
        pg = browser.new_page(viewport={"width": 1000, "height": 760})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.add_init_script("window.MOCK_FAST = true;" + hooks)
        pg.goto(base_url)
        pg.locator("#chevron").click()
        pg.locator("#trayIcon").click()
        expect(pg.locator("#w")).to_be_visible()
        expect(pg.locator(".ad")).to_have_count(2)
        pages.append(pg)
        return pg

    yield _open
    for pg in pages:
        assert pg.errors == []
        pg.close()


def ad(pg, key):
    return pg.locator(f'.ad[data-k="{key}"]')


def test_opens_from_tray_and_shows_live_status(widget):
    pg = widget()
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("HOME-5G")
    expect(pg.locator('.seg button[aria-checked="true"]')).to_have_text("Unigen")
    expect(pg.locator("#nets .net")).to_have_count(2)  # saved networks in range on the Unigen dongle
    expect(pg.locator("#btVer")).to_have_text("Bluetooth 5.4")
    expect(pg.locator("#btDev")).to_have_text("Den Beats Pill")
    pg.mouse.click(100, 100)
    expect(pg.locator("#w")).to_be_hidden()  # like Windows flyouts: clicking elsewhere closes it


def test_use_built_in(widget):
    pg = widget()
    pg.locator('.seg button[data-k="builtin"]').click()
    expect(pg.locator("#wifiMsg")).to_have_text("Wi-Fi now uses the Built-in MediaTek.")
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("Not connected")
    expect(ad(pg, "builtin").locator(".ssid")).to_have_text("HOME-5G")


def test_use_failure_puts_the_switch_back(widget):
    pg = widget('window.MOCK_FAIL = { use_adapter: "Neither adapter is connected. Connect to a network first." };')
    pg.locator('.seg button[data-k="builtin"]').click()
    expect(pg.locator("#wifiMsg")).to_have_text("Neither adapter is connected. Connect to a network first.")
    expect(pg.locator('.seg button[aria-checked="true"]')).to_have_text("Unigen")


def test_disconnect_and_connect_saved(widget):
    pg = widget()
    home = pg.locator("#nets .net").filter(has=pg.get_by_text("HOME-5G", exact=True))
    home.locator("button").click()
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("Not connected")
    expect(home.locator("button .label")).to_have_text("Connect")
    home.locator("button").click()
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("HOME-5G")


def test_bluetooth_switch(widget):
    pg = widget()
    pg.locator("#btSwitch").click()
    expect(pg.locator("#btVer")).to_have_text("Bluetooth 5.2")
    expect(pg.locator("#btSwitch .label")).to_have_text("Use Unigen")


def test_speed_test_sparkline(widget):
    pg = widget()
    pg.locator("#run").click()
    expect(pg.locator("#run .label")).to_have_text("Run test", timeout=10000)
    expect(pg.locator("#spark .line")).to_have_count(2)  # download and upload segments
    assert pg.locator("#dn").inner_text() not in ("", "–")


def test_confirmations_fade_errors_stay(widget):
    pg = widget()
    pg.locator("#btSwitch").click()
    expect(pg.locator("#btMsg")).not_to_be_empty()
    expect(pg.locator("#btMsg")).to_be_empty(timeout=6000)
