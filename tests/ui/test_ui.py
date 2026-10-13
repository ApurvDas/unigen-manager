"""UI tests: ui/index.html against ui/mock-api.js, in the installed Microsoft Edge (no browser download)."""
import functools, http.server, threading
from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.ui
UI = Path(__file__).resolve().parents[2] / "ui"


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="session")
def base_url():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(UI)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/index.html?mock"
    httpd.shutdown()



@pytest.fixture
def open_page(browser, base_url):
    pages = []

    def _open(hooks=""):
        pg = browser.new_page(viewport={"width": 1100, "height": 800})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("dialog", lambda d: (pg.errors.append("unexpected dialog: " + d.message), d.dismiss()))
        pg.add_init_script("window.MOCK_FAST = true;" + hooks)
        pg.goto(base_url)
        expect(pg.locator("#netRows .row").first).to_be_visible()
        pages.append(pg)
        return pg

    yield _open
    for pg in pages:
        assert pg.errors == []
        pg.close()


def hold(page, locator, ms=1700):
    locator.wait_for(state="visible")  # lists load asynchronously after a tab switch
    box = locator.bounding_box()
    page.mouse.move(box["x"] + 5, box["y"] + 5)
    page.mouse.down()
    page.wait_for_timeout(ms)
    page.mouse.up()


def net(page, ssid):
    return page.locator("#netRows .row").filter(has=page.get_by_text(ssid, exact=True))


def saved_row(page, ssid):
    return page.locator("#savedList .row").filter(has=page.get_by_text(ssid, exact=True))


def test_loads_networks_rail_and_versions(open_page):
    pg = open_page()
    expect(pg.locator("#netRows .row")).to_have_count(8)  # 7 named + 1 hidden
    expect(pg.locator(".adapter")).to_have_count(2)
    expect(pg.locator(".adapter").nth(0).locator(".caps")).to_have_text("Wi-Fi 6, Bluetooth 5.4")
    expect(pg.locator(".adapter").nth(1).locator(".caps")).to_have_text("Wi-Fi 6, Bluetooth 5.2")
    expect(pg.locator(".adapter").nth(0).locator(".meta b")).to_have_text("HOME-5G")
    expect(pg.locator("#wifiLabel")).to_have_text("Wi-Fi 6")
    expect(pg.locator("#btLabel")).to_have_text("Bluetooth 5.4")


def test_hostile_ssid_is_text(open_page):
    pg = open_page("window.MOCK_HOSTILE = true;")
    expect(net(pg, "<img src=x onerror=alert(1)>")).to_be_visible()
    assert pg.locator("#netRows img, .map img, #tip img").count() == 0
    pg.locator('.tabs button[data-view="saved"]').click()
    expect(saved_row(pg, "<img src=x onerror=alert(1)>")).to_be_visible()
    pg.keyboard.press("Control+2")
    expect(pg.locator("#paired .row").filter(has=pg.get_by_text("<img src=x onerror=alert(1)>", exact=True))).to_be_visible()
    assert pg.locator("img").count() == 0  # the page has no images of its own: a hostile name never becomes markup


def test_hidden_network_cannot_connect(open_page):
    pg = open_page()
    net(pg, "(hidden network)").click()
    expect(pg.locator("#connect")).to_be_disabled()


def test_connect_saved_network(open_page):
    pg = open_page()
    net(pg, "Maple House").click()
    pg.locator("#connect").click()
    expect(net(pg, "Maple House").locator(".state")).to_have_text("Connected")
    expect(pg.locator("#wifiMsg")).to_have_text("Connected to Maple House.")
    expect(pg.locator(".adapter").nth(0).locator(".meta b")).to_have_text("Maple House")


def test_new_network_password_rules_and_wrong_password(open_page):
    pg = open_page()
    net(pg, "AirFiber-Maple House").click()
    pg.locator("#connect").click()
    expect(pg.locator("#pw")).to_be_visible()
    pg.fill("#pwInput", "short")
    pg.keyboard.press("Enter")
    expect(pg.locator("#pwErr")).to_have_text("The password must be 8 to 63 characters.")
    pg.fill("#pwInput", "wrongpass")
    pg.keyboard.press("Enter")
    expect(pg.locator("#pw")).to_be_hidden()
    expect(pg.locator("#wifiMsg")).to_have_text("Couldn't connect to AirFiber-Maple House. Check the password.")
    expect(pg.locator("#wifiMsg")).to_have_class("msg err")


def test_saved_show_copy_delete(open_page):
    pg = open_page()
    pg.locator('.tabs button[data-view="saved"]').click()
    r = saved_row(pg, "Maple House")
    r.locator(".reveal").click()
    expect(r.locator(".secret")).to_have_text("mock-pass-1234")
    r.locator(".copy").click()
    expect(r.locator(".where")).to_have_text("Both adapters")
    hold(pg, saved_row(pg, "oldrouter").locator(".hold"))
    expect(saved_row(pg, "oldrouter")).to_have_count(0)
    expect(pg.locator("#savedCount")).to_have_text("6")


def test_short_hold_does_not_delete(open_page):
    pg = open_page()
    pg.locator('.tabs button[data-view="saved"]').click()
    hold(pg, saved_row(pg, "oldrouter").locator(".hold"), ms=300)
    pg.wait_for_timeout(1500)
    expect(saved_row(pg, "oldrouter")).to_have_count(1)


def test_delete_failure_keeps_row(open_page):
    pg = open_page('window.MOCK_FAIL = { delete_profile: "Windows refused to delete it." };')
    pg.locator('.tabs button[data-view="saved"]').click()
    hold(pg, saved_row(pg, "oldrouter").locator(".hold"))
    expect(pg.locator("#savedMsg")).to_have_text("Windows refused to delete it.")
    expect(saved_row(pg, "oldrouter")).to_have_count(1)


def test_bt_radio_switch_changes_label(open_page):
    pg = open_page()
    pg.keyboard.press("Control+2")
    expect(pg.locator("#btLabel")).to_have_text("Bluetooth 5.4")
    pg.locator("#tryRadio").click()
    expect(pg.locator("#btLabel")).to_have_text("Bluetooth 5.2")
    expect(pg.locator("#btRadio")).to_have_text("Built-in MediaTek")


def test_bt_switch_needs_admin(open_page):
    pg = open_page("window.MOCK_ADMIN = false;")
    pg.keyboard.press("Control+2")
    expect(pg.locator("#tryRadio")).to_be_disabled()
    expect(pg.locator("#btMsg")).to_contain_text("needs administrator rights")


def test_bt_search_pair_remove(open_page):
    pg = open_page()
    pg.keyboard.press("Control+2")
    expect(pg.locator("#paired .row")).to_have_count(6)
    pg.locator("#btSearch").click()
    expect(pg.locator("#nearby .row")).to_have_count(3)
    pg.locator("#nearby .pair").first.click()
    expect(pg.locator("#paired .row")).to_have_count(7)
    expect(pg.locator("#pairedCount")).to_have_text("7")
    hold(pg, pg.locator("#paired .row").nth(1).locator(".hold"))
    expect(pg.locator("#paired .row")).to_have_count(6)


def test_bt_connect_toggles(open_page):
    pg = open_page()
    pg.keyboard.press("Control+2")
    jbl = pg.locator("#paired .row").filter(has=pg.get_by_text("JBL Go 3", exact=True))
    jbl.locator(".conn").click()
    expect(jbl.locator(".st")).to_have_text("Connected")
    expect(jbl.locator(".conn .label")).to_have_text("Disconnect")


def test_speed_test_draws_and_saves(open_page):
    pg = open_page()
    pg.keyboard.press("Control+3")
    pg.locator("#runTest").click()
    expect(pg.locator("#runTest .label")).to_have_text("Run test", timeout=10000)
    expect(pg.locator("#runTest")).to_be_enabled()
    assert pg.evaluate("document.querySelector('#tp')._m.n") == 40
    expect(pg.locator('#results tr[data-adapter="unigen"] td').nth(3)).not_to_have_text("–")
    expect(pg.locator("#bars .bar")).to_have_count(8)


def test_unplugged_adapter_in_rail(open_page):
    pg = open_page()
    pg.evaluate("window.MOCK_UNPLUG = 'builtin'")
    expect(pg.locator(".adapter").nth(1).locator(".meta b")).to_have_text("Unplugged", timeout=5000)
    pg.locator(".adapter").nth(1).click()
    expect(pg.locator("#wifiMsg")).to_have_text("The Built-in MediaTek isn't plugged in.")


def test_signal_chart_fills_from_polling(open_page):
    pg = open_page()
    pg.keyboard.press("Control+3")
    pg.wait_for_timeout(4500)
    expect(pg.locator("#sig .line")).to_have_count(2)
    assert pg.evaluate("document.querySelector('#sig .line').getAttribute('d').length") > 10


def test_hidden_window_stops_polling(open_page):
    pg = open_page()
    pg.evaluate("""window.n = 0; const a = mockApi.adapters;
        mockApi.adapters = (...x) => { window.n++; return a(...x); };
        mockApi.is_visible = async () => ({ ok: true, data: false });""")
    pg.wait_for_timeout(4500)
    assert pg.evaluate("window.n") == 0
    pg.evaluate("mockApi.is_visible = async () => ({ ok: true, data: true })")
    pg.wait_for_timeout(2600)
    assert pg.evaluate("window.n") >= 1
