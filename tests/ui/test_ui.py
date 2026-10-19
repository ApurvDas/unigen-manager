"""UI tests: ui/index.html against ui/mock-api.js, in the installed Microsoft Edge (no browser download)."""
import functools, http.server, re, threading
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

    def _open(hooks="", **ctx):
        pg = browser.new_page(viewport={"width": 1100, "height": 800}, **ctx)
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
    expect(pg.locator(".adapter").nth(1).locator(".caps")).to_have_text("Bluetooth 5.2")  # off: no Wi-Fi driver to read
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
    pg = open_page("window.MOCK_BOTH_ON = true;")  # copy needs two adapters that are on
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


def wifi_use(pg, key):
    return pg.locator(f'#wifiUse button[data-k="{key}"]')


def bt_use(pg, key):
    return pg.locator(f'#btUse button[data-k="{key}"]')


def rail(pg, key):
    return pg.locator(f'.adapter[data-adapter="{key}"]')


def test_wifi_switch_on_the_wifi_tab(open_page):
    pg = open_page()
    expect(pg.locator("#usingBox")).to_have_count(0)  # the rail's single Using box is gone
    expect(pg.locator("#wifiUse button")).to_have_text(["Dongle", "Built-in"])
    expect(wifi_use(pg, "unigen")).to_have_attribute("aria-checked", "true")
    expect(rail(pg, "unigen").locator(".badge")).to_have_text("In use")
    expect(rail(pg, "builtin").locator(".badge")).to_have_count(0)
    expect(rail(pg, "builtin").locator(".meta b")).to_have_text("Off")
    wifi_use(pg, "builtin").click()
    expect(pg.locator("#wifiUseMsg")).to_have_text("Wi-Fi moved to the Built-in MediaTek.")
    expect(wifi_use(pg, "builtin")).to_have_attribute("aria-checked", "true")
    expect(rail(pg, "builtin").locator(".badge")).to_have_text("In use")
    expect(rail(pg, "unigen").locator(".badge")).to_have_count(0)
    expect(rail(pg, "unigen").locator(".meta b")).to_have_text("Off")
    expect(rail(pg, "builtin")).to_have_attribute("aria-pressed", "true")  # the Wi-Fi page follows the adapter Wi-Fi uses
    expect(pg.locator("#btLabel")).to_have_text("Bluetooth 5.4")  # Bluetooth stays where it was
    pg.keyboard.press("Control+2")
    expect(pg.locator("#btRadio")).to_have_text("Unigen dongle")
    expect(bt_use(pg, "unigen")).to_have_attribute("aria-checked", "true")


def test_wifi_switch_shows_each_step(open_page):
    pg = open_page("window.MOCK_HOLD_STEP = 4;")  # the move waits at step 4 until released
    wifi_use(pg, "builtin").click()
    expect(pg.locator("#wifiUseMsg")).to_have_text("Connecting to HOME-5G…")
    expect(pg.locator("#wifiUse button").first).to_be_disabled()
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#wifiUse button").first).to_be_enabled()  # Wi-Fi works: no waiting for the old one to go off
    expect(pg.locator("#wifiUseMsg")).to_have_text("Wi-Fi moved to the Built-in MediaTek.", timeout=3000)


def test_bluetooth_switch_on_the_bluetooth_tab(open_page):
    pg = open_page("window.MOCK_HOLD_STEP = 2;")  # the move waits at step 2 until released
    pg.keyboard.press("Control+2")
    expect(pg.locator("#btUse button")).to_have_text(["Dongle", "Built-in"])
    expect(bt_use(pg, "unigen")).to_have_attribute("aria-checked", "true")
    expect(pg.locator("#btRadio")).to_have_text("Unigen dongle")
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btUseMsg")).to_have_text("Turning off the Unigen dongle radio…")
    expect(pg.locator("#btUse button").first).to_be_disabled()  # until the move ends
    expect(pg.locator("#wifiUse button").first).to_be_disabled()  # one lock: Wi-Fi waits too
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#btUseMsg")).to_have_text("Bluetooth moved to the Built-in MediaTek.", timeout=6000)
    expect(pg.locator("#btUse button").first).to_be_enabled()
    expect(bt_use(pg, "builtin")).to_have_attribute("aria-checked", "true")
    expect(pg.locator("#btRadio")).to_have_text("Built-in MediaTek")
    expect(pg.locator("#btLabel")).to_have_text("Bluetooth 5.2")
    expect(wifi_use(pg, "unigen")).to_have_attribute("aria-checked", "true")  # Wi-Fi is untouched
    expect(rail(pg, "unigen").locator(".badge")).to_have_text("In use")


def test_wifi_switch_error_restores(open_page):
    msg = "Couldn't finish switching to the Built-in MediaTek. You're still on the Unigen dongle."
    pg = open_page(f'window.MOCK_FAIL = {{ switch_wifi: "{msg}" }};')
    wifi_use(pg, "builtin").click()
    expect(pg.locator("#wifiUseMsg")).to_have_text(msg)
    expect(pg.locator("#wifiUseMsg")).to_have_class("msg err")
    expect(wifi_use(pg, "unigen")).to_have_attribute("aria-checked", "true")
    expect(wifi_use(pg, "builtin")).to_have_attribute("aria-checked", "false")
    expect(pg.locator("#wifiUse button").first).to_be_enabled()
    expect(rail(pg, "unigen").locator(".badge")).to_have_text("In use")


def test_bluetooth_switch_error_restores(open_page):
    msg = "A switch is still finishing. Bluetooth can take up to a minute; try again in a moment."
    pg = open_page(f'window.MOCK_FAIL = {{ switch_bt: "{msg}" }};')
    pg.keyboard.press("Control+2")
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btUseMsg")).to_have_text(msg)
    expect(pg.locator("#btUseMsg")).to_have_class("msg err")
    expect(bt_use(pg, "unigen")).to_have_attribute("aria-checked", "true")
    expect(pg.locator("#btUse button").first).to_be_enabled()


def test_bluetooth_move_that_fails_later_says_so_and_keeps_the_radio(open_page):
    late = "Bluetooth couldn't move and stays on the Unigen dongle. Switch again to retry."
    pg = open_page(f'window.MOCK_BT_FAIL = "{late}";')
    pg.keyboard.press("Control+2")
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btUseMsg")).to_have_text(late)
    expect(pg.locator("#btUseMsg")).to_have_class("msg err")
    expect(bt_use(pg, "unigen")).to_have_attribute("aria-checked", "true")  # shows what Windows really has
    expect(pg.locator("#btUse button").first).to_be_enabled()


def test_switches_need_admin(open_page):
    pg = open_page("window.MOCK_ADMIN = false;")
    expect(pg.locator("#wifiUse button").first).to_be_disabled()
    expect(pg.locator("#wifiUse button").last).to_be_disabled()
    expect(pg.locator("#wifiUse")).to_have_attribute("title", "Switching adapters needs administrator rights.")
    pg.keyboard.press("Control+2")
    expect(pg.locator("#btUse button").first).to_be_disabled()
    expect(pg.locator("#btUse button").last).to_be_disabled()
    expect(pg.locator("#btUse")).to_have_attribute("title", "Switching adapters needs administrator rights.")


def test_using_changed_event_reloads(open_page):
    pg = open_page()
    pg.evaluate("mockApi._setUsing('builtin'); window.onUsingChanged()")  # what the watchdog triggers
    expect(pg.locator("#btLabel")).to_have_text("Bluetooth 5.2")
    expect(wifi_use(pg, "builtin")).to_have_attribute("aria-checked", "true")
    expect(rail(pg, "builtin").locator(".badge")).to_have_text("In use")
    expect(rail(pg, "builtin")).to_have_attribute("aria-pressed", "true")


def test_bluetooth_move_started_elsewhere_reloads_the_tab(open_page):
    pg = open_page()  # the widget (or the watchdog) moved Bluetooth: the page hears the end of the move
    pg.keyboard.press("Control+2")
    expect(bt_use(pg, "unigen")).to_have_attribute("aria-checked", "true")
    pg.evaluate("mockApi._setUsing('builtin', 'bt'); window.onSwitchStep({ kind: 'bt', text: 'Bluetooth moved to the Built-in MediaTek.', done: true, error: false })")
    expect(bt_use(pg, "builtin")).to_have_attribute("aria-checked", "true")
    expect(pg.locator("#btUseMsg")).to_have_text("Bluetooth moved to the Built-in MediaTek.")
    expect(wifi_use(pg, "unigen")).to_have_attribute("aria-checked", "true")


def test_off_adapter_not_selectable(open_page):
    pg = open_page("window.MOCK_LOG = [];")
    pg.wait_for_function("window.MOCK_LOG.includes('scan')")
    off = rail(pg, "builtin")
    expect(off).to_have_class(re.compile(r"\boff\b"))
    expect(off).to_have_attribute("aria-disabled", "true")
    expect(off.locator(".meta b")).to_have_text("Off")
    before = pg.evaluate("window.MOCK_LOG.filter(n => n === 'networks' || n === 'scan').length")
    off.click(force=True)  # aria-disabled: Playwright would otherwise wait for it to be enabled
    pg.wait_for_timeout(300)
    expect(off).to_have_attribute("aria-pressed", "false")
    expect(rail(pg, "unigen")).to_have_attribute("aria-pressed", "true")
    assert pg.evaluate("window.MOCK_LOG.filter(n => n === 'networks' || n === 'scan').length") == before


def test_unplugged_dongle_falls_back_in_mock(open_page):
    pg = open_page("window.MOCK_UNPLUG = 'unigen';")
    expect(pg.locator(".adapter")).to_have_count(1)
    expect(wifi_use(pg, "builtin")).to_have_attribute("aria-checked", "true")


def bt_page(open_page, hooks=""):
    pg = open_page(hooks)
    pg.keyboard.press("Control+2")
    expect(pg.locator("#paired .row")).to_have_count(7 if "HOSTILE" in hooks else 6)  # hostile mode adds a paired device
    return pg


def nearby(pg, name):
    return pg.locator("#nearby .row").filter(has=pg.get_by_text(name, exact=True))


def test_bt_search_pair_remove(open_page):
    pg = bt_page(open_page)
    pg.locator("#btSearch").click()
    expect(pg.locator("#nearby .row")).to_have_count(6)
    expect(pg.locator("#btSearch .label")).to_have_text("Search again")
    nearby(pg, "Galaxy Buds2 Pro").locator(".pair").click()
    expect(pg.locator("#paired .row")).to_have_count(7)
    expect(pg.locator("#pairedCount")).to_have_text("7")
    expect(pg.locator("#btMsg")).to_have_text("Paired with Galaxy Buds2 Pro.")
    hold(pg, pg.locator("#paired .row").nth(1).locator(".hold"))
    expect(pg.locator("#paired .row")).to_have_count(6)


def test_bt_pair_twin_shows_once(open_page):
    # a dual-mode device paired while the list refreshed showed up twice on a real PC
    pg = bt_page(open_page, "window.MOCK_PAIR_TWIN = true;")
    pg.locator("#btSearch").click()
    nearby(pg, "Galaxy Buds2 Pro").locator(".pair").click()
    expect(pg.locator("#btMsg")).to_have_text("Paired with Galaxy Buds2 Pro.")
    expect(pg.locator("#paired .row").filter(has=pg.get_by_text("Galaxy Buds2 Pro", exact=True))).to_have_count(1)
    expect(pg.locator("#pairedCount")).to_have_text("7")


def test_bt_pair_confirm_pin(open_page):
    pg = bt_page(open_page)
    pg.locator("#btSearch").click()
    nearby(pg, "Pixel 8").locator(".pair").click()
    expect(pg.locator(".pairbox")).to_contain_text("Does the device show 482 913?")
    pg.locator(".pairbox .yes").click()
    expect(pg.locator(".pairbox")).to_have_count(0)
    expect(pg.locator("#paired .row")).to_have_count(7)


def test_bt_pair_cancel(open_page):
    pg = bt_page(open_page)
    pg.locator("#btSearch").click()
    nearby(pg, "Pixel 8").locator(".pair").click()
    pg.locator(".pairbox .no").click()
    expect(pg.locator("#btMsg")).to_have_text("Pairing cancelled.")
    expect(nearby(pg, "Pixel 8")).to_have_count(1)
    expect(pg.locator("#paired .row")).to_have_count(6)


def test_bt_pair_display_pin(open_page):
    pg = bt_page(open_page)
    pg.locator("#btSearch").click()
    nearby(pg, "Keys-To-Go K3").locator(".pair").click()
    expect(pg.locator(".pairbox")).to_contain_text("Type 482 913 on the device, then press Enter.")
    expect(pg.locator("#paired .row")).to_have_count(7)


def test_bt_pair_provide_pin_wrong_then_right(open_page):
    pg = bt_page(open_page)
    pg.locator("#btSearch").click()
    nearby(pg, "Car Kit 2").locator(".pair").click()
    pg.locator("#pinIn").fill("1111"); pg.locator("#pinIn").press("Enter")
    expect(pg.locator("#btMsg")).to_have_text("Wrong PIN. Try again.")
    nearby(pg, "Car Kit 2").locator(".pair").click()
    pg.locator("#pinIn").fill("0000"); pg.locator(".pairbox .yes").click()
    expect(pg.locator("#paired .row")).to_have_count(7)


def test_bt_power_off_and_on(open_page):
    pg = bt_page(open_page)
    pg.locator("#btPower").click()
    expect(pg.locator("#bt")).to_have_class(re.compile(r"\boff\b"))
    expect(pg.locator("#btPower")).to_have_attribute("aria-checked", "false")
    expect(pg.locator("#btOnNote")).to_be_visible()
    pg.locator("#btOn").click()
    expect(pg.locator("#bt")).not_to_have_class(re.compile(r"\boff\b"))
    expect(pg.locator("#btRunNote")).to_be_visible()


def test_bt_search_stops_when_leaving_page(open_page):
    pg = bt_page(open_page, "window.MOCK_SEARCH_HOLD = true; window.MOCK_LOG = [];")
    pg.locator("#btSearch").click()
    expect(pg.locator("#btSearch .label")).to_have_text("Searching…")
    pg.keyboard.press("Control+1")
    pg.wait_for_function("window.MOCK_LOG.includes('bt_search_stop')")


def test_hostile_nearby_name_is_text(open_page):
    pg = bt_page(open_page, "window.MOCK_HOSTILE = true;")
    pg.locator("#btSearch").click()
    row = nearby(pg, "<img src=x onerror=alert(2)>")
    expect(row).to_have_count(1)
    row.locator(".pair").click()
    expect(pg.locator(".pairbox")).to_contain_text("482 913")
    assert pg.locator("#nearby img").count() == 0 and not pg.errors


def test_bt_connect_toggles(open_page):
    pg = open_page()
    pg.keyboard.press("Control+2")
    jbl = pg.locator("#paired .row").filter(has=pg.get_by_text("JBL Go 3", exact=True))
    jbl.locator(".conn").click()
    expect(jbl.locator(".st")).to_contain_text("Connected")
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
    pg = open_page("window.MOCK_BOTH_ON = true;")
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


def test_start_runs_a_real_scan(open_page):
    pg = open_page("window.MOCK_LOG = [];")
    pg.wait_for_function("window.MOCK_LOG.includes('scan')")
    assert pg.evaluate("window.MOCK_LOG.indexOf('networks') < window.MOCK_LOG.indexOf('scan')")  # cached list first


def test_rail_shows_app_version(open_page):
    pg = open_page()
    pg.wait_for_function("document.querySelector('#ver').textContent.includes('v0.0.0-mock')")


def paired_row(pg, name):
    return pg.locator("#paired .row").filter(has=pg.get_by_text(name, exact=True))


def test_bt_battery_for_connected_devices(open_page):
    pg = bt_page(open_page)
    expect(paired_row(pg, "Den Beats Pill").locator(".st")).to_contain_text("Connected")
    expect(paired_row(pg, "Den Beats Pill").locator(".batt")).to_have_text("90%")
    expect(paired_row(pg, "Den Beats Pill").locator(".batt")).not_to_have_class(re.compile(r"\blow\b"))
    expect(paired_row(pg, "OnePlus Nord Buds 3r").locator(".batt")).to_have_count(0)  # not connected


def test_bt_refresh_shows_device_connected_elsewhere(open_page):
    # connected from Windows Settings: the list only re-checked every minute, so the row still said Connect
    pg = bt_page(open_page)
    nord = paired_row(pg, "OnePlus Nord Buds 3r")
    expect(nord.locator(".conn")).to_have_text("Connect")
    pg.evaluate("mockApi._setConnected('BT-nord', true)")
    pg.locator("#btRefresh").click()
    expect(nord.locator(".st")).to_have_text("Connected")
    expect(nord.locator(".conn")).to_have_text("Disconnect")
    expect(pg.locator("#btRefresh")).to_have_text("Refresh")


def test_opening_the_window_refreshes_at_once(open_page):
    # hidden, the page stops polling; Python calls onMainShown when the tray or the shortcut opens it
    pg = bt_page(open_page)
    pg.evaluate("mockApi._setConnected('BT-nord', true); window.onMainShown()")
    expect(paired_row(pg, "OnePlus Nord Buds 3r").locator(".st")).to_have_text("Connected", timeout=2000)


def test_bt_battery_after_connect_and_low(open_page):
    pg = bt_page(open_page)
    jbl = paired_row(pg, "JBL Go 3")
    jbl.locator(".conn").click()
    expect(jbl.locator(".batt")).to_have_text("15%")
    expect(jbl.locator(".batt")).to_have_class(re.compile(r"\blow\b"))


OTHER = "window.MOCK_OTHER_RADIO = true;"


def test_bt_row_from_other_radio_offers_repair(open_page):
    pg = bt_page(open_page, OTHER)
    nord = paired_row(pg, "OnePlus Nord Buds 3r")
    expect(nord.locator(".st")).to_have_text("Not paired with the dongle")
    expect(nord.locator(".pair .label")).to_have_text("Re-pair")
    expect(nord.locator(".conn")).to_have_count(0)
    expect(paired_row(pg, "Tribit StormBox Mini+").locator(".conn")).to_have_count(1)
    expect(pg.locator("#btAway")).to_have_text("2 devices aren't paired with the dongle yet. "
                                               "They were paired with the Built-in MediaTek; re-pair each once to use it here.")


def test_bt_repair_explains_then_pairs_in_place(open_page):
    pg = bt_page(open_page, OTHER)
    nord = paired_row(pg, "OnePlus Nord Buds 3r")
    nord.locator(".pair").click()
    box = pg.locator(".pairbox.explain")
    expect(box).to_contain_text("OnePlus Nord Buds 3r isn't connected to the Unigen dongle.")
    expect(box).to_contain_text("It was paired with the Built-in MediaTek.")
    expect(box).to_contain_text("Your pairing with the built-in radio stays.")
    expect(box.locator("li")).to_have_count(3)
    box.get_by_role("button", name="Pair now").click()
    expect(pg.locator(".pairbox")).to_have_count(0)
    expect(pg.locator("#btMsg")).to_have_text("Paired with OnePlus Nord Buds 3r. It now works on both radios.")
    expect(nord.locator(".st")).to_have_text("Connected")
    expect(nord.locator(".conn .label")).to_have_text("Disconnect")
    expect(pg.locator("#paired .row")).to_have_count(6)
    expect(pg.locator("#paired .row").nth(1).locator(".title")).to_have_text("OnePlus Nord Buds 3r")  # same place in the list
    expect(pg.locator("#btAway")).to_contain_text("1 device isn't paired with the dongle yet.")


def test_bt_repair_status_opens_box_and_cancel_closes(open_page):
    pg = bt_page(open_page, OTHER)
    jbl = paired_row(pg, "JBL Go 3")
    jbl.locator(".why").click()
    expect(pg.locator(".pairbox.explain")).to_have_count(1)
    pg.get_by_role("button", name="Cancel").click()
    expect(pg.locator(".pairbox")).to_have_count(0)
    expect(jbl.locator(".st")).to_have_text("Not paired with the dongle")


def test_bt_note_follows_the_radio_in_use(open_page):
    pg = bt_page(open_page, OTHER)
    pg.evaluate("mockApi._setUsing('builtin'); window.onUsingChanged()")
    expect(pg.locator("#btRadio")).to_have_text("Built-in MediaTek")
    expect(paired_row(pg, "JBL Go 3").locator(".st")).to_have_text("Not paired with the built-in radio")
    expect(pg.locator("#btAway")).to_contain_text("2 devices aren't paired with the built-in radio yet.")


def test_bt_stale_connect_explains_and_opens_the_box(open_page):
    pg = bt_page(open_page)
    tribit = paired_row(pg, "Tribit StormBox Mini+")
    expect(tribit.locator(".conn")).to_have_text("Connect")
    pg.evaluate("mockApi.is_visible = async () => ({ ok: true, data: false })")  # no poll may refresh the row first
    pg.evaluate("mockApi._setHere('BT-tribit', false)")  # moved behind the app's back
    tribit.locator(".conn").click()
    expect(pg.locator("#btMsg")).to_have_text("Tribit StormBox Mini+ is paired with the Built-in MediaTek, not this one. "
                                               "Put it in pairing mode, then press Re-pair.")
    expect(paired_row(pg, "Tribit StormBox Mini+").locator(".st")).to_have_text("Not paired with the dongle")
    expect(pg.locator(".pairbox.explain")).to_have_count(1)


def test_bt_refresh_rebuilds_a_row_whose_radio_changed(open_page):
    pg = bt_page(open_page, OTHER)
    pg.evaluate("mockApi._setHere('BT-nord', true)")  # paired here from Windows Settings
    pg.locator("#btRefresh").click()
    expect(paired_row(pg, "OnePlus Nord Buds 3r").locator(".conn")).to_have_count(1)
    expect(pg.locator("#btAway")).to_contain_text("1 device isn't paired with the dongle yet.")


def test_hostile_name_in_repair_box_is_text(open_page):
    pg = bt_page(open_page, OTHER + "window.MOCK_HOSTILE = true;")
    pg.evaluate("mockApi._setHere('BT-evil', false)")
    pg.locator("#btRefresh").click()
    row = paired_row(pg, "<img src=x onerror=alert(1)>")
    row.locator(".pair").click()
    expect(pg.locator(".pairbox.explain")).to_contain_text("<img src=x onerror=alert(1)> isn't connected")
    assert pg.locator("img").count() == 0


# ---- the dongle's status ----
def test_dongle_connected_in_the_rail(open_page):
    pg = open_page()
    expect(pg.locator("#dongle")).to_have_text("Dongle connected")
    expect(pg.locator("#dongle")).to_have_attribute("data-state", "connected")
    expect(wifi_use(pg, "unigen")).to_be_enabled()
    expect(wifi_use(pg, "unigen")).to_have_attribute("title", "")
    pg.keyboard.press("Control+2")
    expect(bt_use(pg, "unigen")).to_be_enabled()


def test_unplugged_dongle_shows_in_the_rail_and_disables_its_buttons(open_page):
    pg = open_page("window.MOCK_UNPLUG = 'unigen';")
    expect(pg.locator("#dongle")).to_have_text("Dongle not plugged in")
    expect(pg.locator("#dongle")).to_have_attribute("data-state", "unplugged")
    expect(pg.locator(".adapter")).to_have_count(1)
    expect(pg.locator("#wifiUseRow")).to_be_visible()  # one adapter left, but the disabled Dongle button is still shown
    expect(wifi_use(pg, "unigen")).to_be_disabled()
    expect(wifi_use(pg, "unigen")).to_have_attribute("title", "Plug in the dongle.")
    expect(wifi_use(pg, "builtin")).to_be_enabled()  # Built-in stays usable
    expect(wifi_use(pg, "builtin")).to_have_attribute("aria-checked", "true")
    pg.keyboard.press("Control+2")
    expect(bt_use(pg, "unigen")).to_be_disabled()
    expect(bt_use(pg, "unigen")).to_have_attribute("title", "Plug in the dongle.")
    expect(bt_use(pg, "builtin")).to_be_enabled()
    expect(bt_use(pg, "builtin")).to_have_attribute("aria-checked", "true")


def test_dongle_not_responding_in_the_rail(open_page):
    pg = open_page("window.MOCK_DONGLE = 'not_responding';")
    expect(pg.locator("#dongle")).to_have_text("Dongle not responding. Unplug it and plug it back in.")
    expect(pg.locator("#dongle")).to_have_attribute("data-state", "not_responding")
    expect(wifi_use(pg, "unigen")).to_be_disabled()
    expect(wifi_use(pg, "unigen")).to_have_attribute("title", "Unplug the dongle and plug it back in.")


def test_dongle_status_follows_the_watchdog_and_looks_again(open_page):
    pg = open_page()
    pg.evaluate("mockApi._setDongle('unplugged'); window.onUsingChanged()")  # the watchdog's unplug notice
    expect(pg.locator("#dongle")).to_have_text("Dongle not plugged in")
    expect(pg.locator(".adapter")).to_have_count(1)
    pg.evaluate("mockApi._setDongle('connected')")  # plugged back in: nothing announces it, the page looks again
    expect(pg.locator("#dongle")).to_have_text("Dongle connected", timeout=8000)
    expect(pg.locator(".adapter")).to_have_count(2)
    expect(wifi_use(pg, "unigen")).to_be_enabled()


def test_switches_need_admin_and_a_dongle_each_say_why(open_page):
    pg = open_page("window.MOCK_ADMIN = false; window.MOCK_UNPLUG = 'unigen';")
    expect(wifi_use(pg, "builtin")).to_be_disabled()
    expect(pg.locator("#wifiUse")).to_have_attribute("title", "Switching adapters needs administrator rights.")
    expect(wifi_use(pg, "unigen")).to_have_attribute("title", "Plug in the dongle.")


# ---- the stepped progress bar and the Bluetooth lock-out ----
def blocks(pg, bar):
    return pg.locator(f"#{bar} .blk")


def states(pg, bar):
    return pg.eval_on_selector_all(f"#{bar} .blk", "bs => bs.map(b => b.dataset.s)")


def test_wifi_bar_has_one_block_per_step_and_advances(open_page):
    pg = open_page("window.MOCK_HOLD_STEP = 3;")
    wifi_use(pg, "builtin").click()
    expect(blocks(pg, "wifiSteps")).to_have_count(5)  # turn on, wait, find, connect, turn the old one off
    expect(pg.locator("#wifiSteps .steps-title")).to_have_text("Switching Wi-Fi")
    expect(pg.locator("#wifiSteps .steps-count")).to_contain_text("3/5 · ")
    expect(pg.locator("#wifiSteps .steps-label")).to_have_text("Finding HOME-5G")
    assert states(pg, "wifiSteps") == ["done", "done", "current", "empty", "empty"]
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#wifiSteps .steps-fold")).to_be_visible(timeout=4000)
    expect(pg.locator("#wifiSteps .steps-fold-t")).to_have_text("Wi-Fi moved to the Built-in MediaTek")
    expect(pg.locator("#wifiSteps .steps-body")).to_be_hidden()  # folded into one line


def test_bluetooth_bar_four_steps_then_folds_and_goes(open_page):
    pg = open_page("window.MOCK_HOLD_STEP = 2;")
    pg.keyboard.press("Control+2")
    bt_use(pg, "builtin").click()
    expect(blocks(pg, "btSteps")).to_have_count(4)
    expect(pg.locator("#btSteps .steps-title")).to_have_text("Moving Bluetooth")
    expect(pg.locator("#btSteps .steps-count")).to_contain_text("2/4 · ")
    expect(pg.locator("#btSteps .steps-label")).to_have_text("Turning off the Unigen dongle radio")
    assert states(pg, "btSteps") == ["done", "current", "empty", "empty"]
    assert pg.evaluate("getComputedStyle(document.querySelector('#btSteps')).getPropertyValue('--accent')").strip().lower() == "#d55181"  # the target's colour (--bi)
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#btSteps .steps-fold")).to_be_visible(timeout=6000)
    expect(pg.locator("#btSteps .steps-fold-t")).to_have_text("Bluetooth moved to the Built-in MediaTek")
    expect(pg.locator("#btSteps")).to_be_hidden(timeout=9000)  # lingers a few seconds, then fades out


def test_bluetooth_steps_with_nothing_to_do_are_skipped(open_page):
    pg = open_page("window.MOCK_HOLD_STEP = 3;")
    pg.evaluate("mockApi._setConnected('BT-beats', false)")  # no device connected: nothing to disconnect or reconnect
    pg.keyboard.press("Control+2")
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btSteps .steps-count")).to_contain_text("3/4 · ")
    assert states(pg, "btSteps") == ["skipped", "done", "current", "empty"]
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#btSteps .steps-fold")).to_be_visible(timeout=6000)


def test_failed_step_shows_red_block_message_and_try_again(open_page):
    late = "Windows didn't turn off the Unigen dongle radio, usually because audio is still playing through it."
    pg = open_page(f'window.MOCK_BT_FAIL = "{late}"; window.MOCK_FAIL_STEP = 2;')
    pg.keyboard.press("Control+2")
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btSteps .retry")).to_be_visible(timeout=6000)
    assert states(pg, "btSteps") == ["done", "failed", "empty", "empty"]
    expect(pg.locator("#btSteps .steps-count")).to_have_text("2/4 · failed")
    expect(pg.locator("#btSteps")).to_have_attribute("data-bar", "fail")
    expect(pg.locator("#btUseMsg")).to_have_text(late)  # the message stays visible next to the bar
    expect(pg.locator("#btUseMsg")).to_have_class("msg err")
    expect(bt_use(pg, "unigen")).to_have_attribute("aria-checked", "true")
    pg.evaluate("window.MOCK_BT_FAIL = null")
    pg.locator("#btSteps .retry").click()  # Try again repeats the same move
    expect(pg.locator("#btSteps .steps-fold-t")).to_have_text("Bluetooth moved to the Built-in MediaTek", timeout=6000)
    expect(bt_use(pg, "builtin")).to_have_attribute("aria-checked", "true")


def test_wifi_failure_names_the_step(open_page):
    msg = "Couldn't finish switching to the Built-in MediaTek. You're still on the Unigen dongle."
    pg = open_page(f'window.MOCK_WIFI_FAIL = "{msg}"; window.MOCK_FAIL_STEP = 3;')
    wifi_use(pg, "builtin").click()
    expect(pg.locator("#wifiSteps .retry")).to_be_visible(timeout=6000)
    assert states(pg, "wifiSteps") == ["done", "done", "failed", "empty", "empty"]
    expect(pg.locator("#wifiSteps .steps-label")).to_have_text("Finding HOME-5G")
    expect(wifi_use(pg, "unigen")).to_have_attribute("aria-checked", "true")
    expect(pg.locator("#wifiUse button").first).to_be_enabled()


def test_bluetooth_actions_are_off_while_it_moves_and_back_after(open_page):
    pg = open_page("window.MOCK_HOLD_STEP = 2;")
    pg.keyboard.press("Control+2")
    expect(pg.locator("#paired .row")).to_have_count(6)
    pg.evaluate("setMsg($('#btMsg'), 'Bluetooth isn\\'t ready yet.', true)")  # an old error from before the move
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btSteps .steps-count")).to_contain_text("2/4")
    for sel in ("#paired .conn", "#paired .hold", "#btPower"):
        for el in pg.locator(sel).all():
            expect(el).to_be_disabled()
    pg.evaluate("document.querySelector('#paired').insertAdjacentHTML('beforeend', pairedRow({ id: 'new', name: 'New', kind: 'Audio', connected: false }))")
    expect(pg.locator("#paired .row").last.locator(".conn")).to_be_disabled()  # rows that appear mid-move are locked too
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#btSteps .steps-fold")).to_be_visible(timeout=6000)
    for sel in ("#paired .conn", "#paired .hold", "#btPower"):
        for el in pg.locator(sel).all():
            expect(el).to_be_enabled()
    expect(pg.locator("#btMsg")).to_have_text("")  # no stale error under the result


def test_pressing_a_switch_while_a_move_runs_shows_the_running_bar_not_an_error(open_page):
    pg = open_page("window.MOCK_LOG = [];")
    pg.keyboard.press("Control+2")
    pg.evaluate("window.onSwitchStep({ kind: 'bt', text: 'Turning off the Unigen dongle radio…', done: false, error: false, step: 2, of: 4, label: 'Turning off the Unigen dongle radio' })")
    expect(pg.locator("#btSteps .steps-count")).to_contain_text("2/4")  # the watchdog's move shows its bar here too
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btSteps .steps-title")).to_have_text("Already moving Bluetooth · 2/4")
    expect(pg.locator("#btUseMsg")).not_to_have_class("msg err")
    assert "switch_bt" not in pg.evaluate("window.MOCK_LOG")  # nothing was asked of the backend
    pg.evaluate("window.onSwitchStep({ kind: 'bt', text: 'Bluetooth moved to the Unigen dongle.', done: true, error: false, step: 4, of: 4, label: 'x' })")
    expect(pg.locator("#btSteps .steps-fold-t")).to_have_text("Bluetooth moved to the Unigen dongle", timeout=3000)


def test_a_move_from_the_watchdog_that_fails_shows_its_failed_block(open_page):
    pg = open_page()
    pg.keyboard.press("Control+2")
    pg.evaluate("window.onSwitchStep({ kind: 'bt', text: 'Starting the Unigen dongle radio…', done: false, error: false, step: 3, of: 4, label: 'Starting the Unigen dongle radio' })")
    pg.evaluate("window.onSwitchStep({ kind: 'bt', text: 'The Unigen dongle radio didn\\'t start.', done: true, error: true, step: 3, of: 4, label: 'Starting the Unigen dongle radio' })")
    assert states(pg, "btSteps") == ["skipped", "skipped", "failed", "empty"]
    expect(pg.locator("#btSteps .retry")).to_be_visible()


def test_reduced_motion_has_no_hatch_sweep_or_shake(open_page):
    pg = open_page("window.MOCK_HOLD_STEP = 2;", reduced_motion="reduce")
    pg.keyboard.press("Control+2")
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btSteps .steps-count")).to_contain_text("2/4")
    cur = "#btSteps .blk[data-s='current'] b"
    assert pg.evaluate(f"getComputedStyle(document.querySelector(\"{cur}\"), '::after').animationName") == "none"  # no hatch
    assert pg.evaluate(f"document.querySelector(\"{cur}\").style.transform") == ""  # no sweep: the fill isn't animated
    assert pg.evaluate("document.querySelector('#btSteps').getAnimations({ subtree: true }).length") == 0
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#btSteps .steps-fold")).to_be_visible(timeout=6000)


def test_motion_is_on_without_reduced_motion(open_page):
    pg = open_page("window.MOCK_HOLD_STEP = 2;")
    pg.keyboard.press("Control+2")
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btSteps .steps-count")).to_contain_text("2/4")
    cur = "#btSteps .blk[data-s='current'] b"
    assert pg.evaluate(f"getComputedStyle(document.querySelector(\"{cur}\"), '::after').animationName") == "hatch"
    pg.wait_for_timeout(300)
    assert pg.evaluate(f"document.querySelector(\"{cur}\").style.transform") not in ("", "scaleX(0)")  # the fill sweeps, never to the end
    assert float(pg.evaluate(f"document.querySelector(\"{cur}\").style.transform").split("(")[1].rstrip(")")) < 0.71


def test_switch_is_square_with_a_hard_shadow_in_the_adapters_colour(open_page):
    pg = open_page()
    seg = pg.locator("#wifiUse")
    css = lambda prop: pg.evaluate(f"getComputedStyle(document.querySelector('#wifiUse')).{prop}")
    assert css("borderTopWidth") == "2px" and css("borderTopLeftRadius") == "0px"
    shadow = css("boxShadow")
    assert "4px 4px 0px" in shadow and "rgb(144, 133, 233)" in shadow  # --uni for the Dongle
    wifi_use(pg, "builtin").click()
    expect(pg.locator("#wifiUseMsg")).to_have_text("Wi-Fi moved to the Built-in MediaTek.")
    assert "rgb(213, 81, 129)" in css("boxShadow")  # --bi once the Built-in is chosen
    pg.mouse.move(0, 0)
    box = wifi_use(pg, "builtin").bounding_box()  # the chosen button: pressing it starts nothing
    pg.mouse.move(box["x"] + 5, box["y"] + 5)
    pg.mouse.down()
    pg.wait_for_timeout(300)
    assert "0px 0px 0px" in css("boxShadow")  # pressed: it sank onto its shadow
    pg.mouse.up()
    pg.wait_for_timeout(900)
    assert abs(float(css("boxShadow").split("px")[0].split()[-1]) - 4) < 0.5  # and springs back


# ---- the design system: square, hard shadows only on pressables, one press, five type sizes ----
SIZES = {"11px", "12px", "14px", "24px", "48px"}
ROUND = """() => [...document.querySelectorAll('body *')].filter(e => !e.closest('svg') &&
    ['TopLeft', 'TopRight', 'BottomLeft', 'BottomRight'].some(c => getComputedStyle(e)['border' + c + 'Radius'] !== '0px')).map(e => e.tagName + '.' + e.className)"""
TEXT_SIZES = """() => [...new Set([...document.querySelectorAll('body *')].filter(e => getComputedStyle(e).display !== 'none' &&
    [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())).map(e => getComputedStyle(e).fontSize))]"""


def shadow(pg, sel):
    return pg.evaluate(f"getComputedStyle(document.querySelector('{sel}')).boxShadow")


def test_nothing_is_rounded_and_text_uses_five_sizes(open_page):
    pg = open_page("window.MOCK_BOTH_ON = true;")
    for tab in ("Control+1", "Control+2", "Control+3"):
        pg.keyboard.press(tab)
        pg.wait_for_timeout(300)
        assert pg.evaluate(ROUND) == []  # only the chart curves (inside the SVGs) are curved
        assert set(pg.evaluate(TEXT_SIZES)) <= SIZES, pg.evaluate(TEXT_SIZES)
    pg.keyboard.press("Control+1")
    pg.locator('.tabs button[data-view="saved"]').click()
    expect(pg.locator("#savedList .row").first).to_be_visible()
    assert pg.evaluate(ROUND) == [] and set(pg.evaluate(TEXT_SIZES)) <= SIZES


def test_every_button_and_segmented_control_has_a_hard_shadow_that_collapses_on_press(open_page):
    pg = open_page()
    net(pg, "Maple House").click()  # a network that can be connected: the primary button is enabled
    hard = re.compile(r"^rgb\(\d+, \d+, \d+\) (\d+)px (\d+)px 0px 0px$")  # a colour, an offset, no blur, no spread
    for sel in ("#scan", "#connect", "#wifiUse", ".tabs"):
        m = hard.match(shadow(pg, sel))
        assert m and m.group(1) == m.group(2) and int(m.group(1)) >= 3, (sel, shadow(pg, sel))
    assert "4px 4px 0px" in shadow(pg, "#connect") and "rgb(79, 179, 200)" in shadow(pg, "#connect")  # primary: --b5
    assert "3px 3px 0px" in shadow(pg, "#scan")  # a small button
    for sel in ("#scan", "#connect"):  # pressing sinks the button onto its shadow
        box = pg.locator(sel).bounding_box()
        pg.mouse.move(box["x"] + 8, box["y"] + 8)
        pg.mouse.down()
        pg.wait_for_timeout(300)
        assert "0px 0px 0px" in shadow(pg, sel), sel
        assert pg.evaluate(f"getComputedStyle(document.querySelector('{sel}')).translate") != "none"  # and moved by its offset
        pg.mouse.up()
        pg.wait_for_timeout(900)
        assert re.match(r"^rgb\(.*\) [34]px [34]px 0px 0px$", shadow(pg, sel)), sel
    pg.locator('.tabs button[data-view="saved"]').click()  # the tabs are the same control as the adapter switch
    expect(pg.locator('.tabs button[aria-selected="true"]')).to_have_text(re.compile("Saved"))
    assert pg.evaluate("document.querySelector('.tabs').classList.contains('seg')")


def test_the_selected_adapter_card_wears_its_adapters_colour(open_page):
    pg = open_page()
    assert "rgb(144, 133, 233)" in shadow(pg, ".ad-ind")  # --uni
    wifi_use(pg, "builtin").click()
    expect(rail(pg, "builtin")).to_have_attribute("aria-pressed", "true")
    pg.wait_for_function("getComputedStyle(document.querySelector('.ad-ind')).boxShadow.includes('rgb(213, 81, 129)')")  # --bi
    assert "0px" not in shadow(pg, ".ad-ind").split(")")[1].split()[0]  # a hard offset, not collapsed


def test_the_signal_meter_is_four_square_blocks_lit_by_strength(open_page):
    pg = open_page()
    rows = pg.locator("#netRows .row")
    for i in range(rows.count()):
        assert rows.nth(i).locator(".meter i").count() == 4
    lit = pg.eval_on_selector_all("#netRows .row", "rs => rs.map(r => r.querySelectorAll('.meter i.lit').length)")
    assert lit[0] == 4 and lit[-1] == 1 and lit == sorted(lit, reverse=True)  # HOME-5G 96% down to the hidden network at 6%
    w = pg.evaluate("[...document.querySelectorAll('.meter i')].map(i => i.offsetWidth + 'x' + i.offsetHeight)")
    assert set(w) == {"10x10"}


def test_the_battery_is_square_cells(open_page):
    pg = bt_page(open_page)
    beats = paired_row(pg, "Den Beats Pill").locator(".batt svg .cell")
    assert beats.count() == 4 and pg.eval_on_selector_all("#paired .batt svg .cell:not(.off)", "c => c.length") == 4  # 90%
    paired_row(pg, "JBL Go 3").locator(".conn").click()
    expect(paired_row(pg, "JBL Go 3").locator(".batt")).to_have_text("15%")
    assert paired_row(pg, "JBL Go 3").locator(".batt svg .cell:not(.off)").count() == 1
    assert pg.evaluate("[...document.querySelectorAll('.batt svg rect')].every(r => !r.getAttribute('rx'))")


def test_a_label_swap_has_no_blur(open_page):
    pg = open_page()
    seen = pg.evaluate("""() => new Promise(done => {
        const l = document.querySelector('#scan .label'), seen = new Set();
        const t = setInterval(() => seen.add(getComputedStyle(l).filter), 10);
        document.querySelector('#scan').click();
        setTimeout(() => { clearInterval(t); done([...seen]); }, 700);
    })""")
    assert seen == ["none"]


def test_searching_shows_the_moving_hatch_strip(open_page):
    pg = bt_page(open_page, "window.MOCK_SEARCH_HOLD = true;")
    pg.locator("#btSearch").click()
    expect(pg.locator("#btProg")).to_be_visible()
    assert pg.evaluate("getComputedStyle(document.querySelector('#btProg i'), '::after').animationName") == "hatch"
    assert pg.evaluate("getComputedStyle(document.querySelector('#btProg')).height") == "10px"


def test_reduced_motion_presses_without_moving_and_the_strip_stands_still(open_page):
    pg = open_page("window.MOCK_SEARCH_HOLD = true;", reduced_motion="reduce")
    pg.keyboard.press("Control+2")
    expect(pg.locator("#paired .row")).to_have_count(6)
    pg.locator("#btSearch").click()
    expect(pg.locator("#btProg")).to_be_visible()
    assert pg.evaluate("getComputedStyle(document.querySelector('#btProg i'), '::after').animationName") == "none"
    before = shadow(pg, "#btRefresh")
    box = pg.locator("#btRefresh").bounding_box()
    pg.mouse.move(box["x"] + 8, box["y"] + 8)
    pg.mouse.down()
    pg.wait_for_timeout(300)
    assert shadow(pg, "#btRefresh") == before and pg.evaluate("getComputedStyle(document.querySelector('#btRefresh')).translate") in ("none", "0px")
    pg.mouse.up()


# ---- traffic ----
def traffic_page(open_page, hooks=""):
    pg = open_page(hooks)
    pg.keyboard.press("Control+4")
    expect(pg.locator("#traffic")).to_be_visible()
    return pg


def test_traffic_nav_ctrl_4_and_the_other_pages_still_work(open_page):
    pg = open_page()
    expect(pg.locator('nav button[data-go="traffic"]')).to_have_text("Traffic Ctrl 4")
    pg.locator('nav button[data-go="traffic"]').click()
    expect(pg.locator("#traffic")).to_be_visible()
    expect(pg.locator('nav button[aria-current="page"]')).to_have_attribute("data-go", "traffic")
    expect(pg.locator("#wifi")).to_be_hidden()
    pg.keyboard.press("Control+1")
    expect(pg.locator("#wifi")).to_be_visible()
    expect(pg.locator("#traffic")).to_be_hidden()
    pg.keyboard.press("Control+4")
    expect(pg.locator("#traffic")).to_be_visible()
    expect(pg.locator("#trafficTitle")).to_have_text("Traffic on Unigen dongle")


def test_traffic_numbers_update_in_place(open_page):
    pg = traffic_page(open_page)
    pg.evaluate("mockApi._setRate(4200000, 300000)")
    expect(pg.locator("#trafDown")).to_have_text("4.2", timeout=4000)
    expect(pg.locator("#trafDownU")).to_have_text("MB/s")
    expect(pg.locator("#trafUp")).to_have_text("300")
    expect(pg.locator("#trafUpU")).to_have_text("KB/s")
    pg.evaluate("document.querySelector('#trafDown').dataset.same = '1'")  # the element is kept, only its text changes
    pg.evaluate("mockApi._setRate(8000000, 1000000)")
    expect(pg.locator("#trafDown")).to_have_text("8.0", timeout=4000)
    expect(pg.locator("#trafUp")).to_have_text("1.0")
    expect(pg.locator("#trafUpU")).to_have_text("MB/s")
    assert pg.evaluate("document.querySelector('#trafDown').dataset.same") == "1"
    assert pg.evaluate("document.querySelector('#trafDown').getAnimations().length") == 0  # no flash on a number that moves every second


def test_traffic_unit_toggle_switches_text_and_the_wifi_line(open_page):
    pg = traffic_page(open_page)
    pg.evaluate("mockApi._setRate(4200000, 300000)")
    expect(pg.locator("#trafDown")).to_have_text("4.2", timeout=4000)
    expect(pg.locator('#trafficUnit button[aria-checked="true"]')).to_have_text("MB/s")
    pg.locator('#trafficUnit button[data-k="bits"]').click()
    expect(pg.locator("#trafDown")).to_have_text("33.6")
    expect(pg.locator("#trafDownU")).to_have_text("Mbps")
    expect(pg.locator("#trafUp")).to_have_text("2.4")
    expect(pg.locator('#trafficUnit button[aria-checked="true"]')).to_have_text("Mbps")
    expect(pg.locator("#trafSub")).to_have_text("Mbps")
    pg.keyboard.press("Control+1")
    expect(pg.locator("#wifiLive")).to_have_text("↓ 33.6 Mbps · ↑ 2.4 Mbps")
    pg.keyboard.press("Control+4")
    pg.locator('#trafficUnit button[data-k="bytes"]').click()  # and back
    expect(pg.locator("#trafUpU")).to_have_text("KB/s")
    pg.evaluate("window.onTrafficUnit('bits')")  # what Python pushes when the widget changes the unit
    expect(pg.locator("#trafUpU")).to_have_text("Mbps")


def test_traffic_chart_has_sixty_points_in_the_adapters_colour(open_page):
    pg = traffic_page(open_page)
    expect(pg.locator("#traf .line")).to_have_count(2, timeout=4000)
    assert pg.evaluate("[...document.querySelectorAll('#traf .line')].map(l => l.getAttribute('d').match(/[ML]/g).length)") == [60, 60]
    assert pg.evaluate("[...document.querySelectorAll('#traf .line')].map(l => l.getAttribute('stroke'))") == ["var(--uni)", "var(--ink)"]
    assert pg.evaluate("document.querySelector('#traf .line:last-of-type').getAttribute('stroke-opacity')") == "0.6"
    assert pg.locator("#traf rect.end").count() == 1  # the newest point has a square marker
    assert pg.evaluate("document.querySelector('#traf rect.end').getAttribute('rx')") is None


def test_traffic_chart_scrolls_one_step_per_tick_and_reduced_motion_only_redraws(open_page):
    pg = traffic_page(open_page)
    pg.wait_for_function("document.querySelector('#traf .shift') && document.querySelector('#traf .shift').style.transform.includes('translateX')", timeout=5000)
    pg2 = open_page(reduced_motion="reduce")
    pg2.keyboard.press("Control+4")
    expect(pg2.locator("#traf .line")).to_have_count(2, timeout=4000)
    pg2.wait_for_timeout(2600)  # a few ticks have redrawn it
    assert pg2.evaluate("document.querySelector('#traf .shift').style.transform") == ""
    assert pg2.evaluate("document.querySelector('#traf').getAnimations({ subtree: true }).length") == 0


def test_traffic_today_rows_and_note(open_page):
    pg = traffic_page(open_page)
    rows = pg.locator("#todayRows .row")
    expect(rows).to_have_count(2)
    expect(rows.nth(0).locator(".title")).to_have_text("Unigen dongle")
    expect(rows.nth(1).locator(".title")).to_have_text("Built-in MediaTek")
    expect(rows.nth(0).locator(".dn")).to_have_text(re.compile(r"^\d+\.\d+ GB$"))
    expect(rows.nth(0).locator(".up")).to_have_text(re.compile(r"^\d+\.\d MB$"))
    assert pg.evaluate("[...document.querySelectorAll('#todayRows .pip')].map(p => p.style.getPropertyValue('--pip'))") == ["var(--uni)", "var(--bi)"]
    expect(pg.locator(".today .note")).to_have_text("Counted while Unigen Manager runs")
    pg.locator("#todayRows .row").first.evaluate("r => r.dataset.same = '1'")
    pg.wait_for_timeout(1500)
    assert pg.evaluate("document.querySelector('#todayRows .row').dataset.same") == "1"  # rows are updated in place


def test_traffic_empty_and_measuring_states(open_page):
    pg = traffic_page(open_page, "window.MOCK_TRAFFIC = 'none';")
    expect(pg.locator("#trafEmpty")).to_have_text("No Wi-Fi adapter is on")
    expect(pg.locator("#traf")).to_be_hidden()
    expect(pg.locator("#trafDown")).to_have_text("–")
    expect(pg.locator("#trafficTitle")).to_have_text("Traffic")
    pg.keyboard.press("Control+1")
    expect(pg.locator("#wifiLive")).to_be_hidden()
    pg = traffic_page(open_page, "window.MOCK_TRAFFIC = 'measuring';")
    expect(pg.locator("#trafEmpty")).to_have_text("Measuring…")
    expect(pg.locator("#traf")).to_be_hidden()
    expect(pg.locator("#trafDown")).to_have_text("–")
    pg.keyboard.press("Control+1")
    expect(pg.locator("#wifiLive")).to_have_text("Measuring…")


def test_wifi_page_has_one_live_line_under_the_adapter_switch(open_page):
    pg = open_page()
    pg.evaluate("mockApi._setRate(4200000, 300000)")
    expect(pg.locator("#wifiLive")).to_have_text("↓ 4.2 MB/s · ↑ 300 KB/s", timeout=4000)
    below = pg.evaluate("document.querySelector('#wifiLive').getBoundingClientRect().top >= document.querySelector('#wifiUse').getBoundingClientRect().bottom")
    assert below and pg.evaluate("getComputedStyle(document.querySelector('#wifiLive')).textTransform") == "uppercase"  # a caps line
    assert pg.evaluate("getComputedStyle(document.querySelector('#wifiLive')).fontSize") == "11px"
    wifi_use(pg, "builtin").click()  # follows the adapter in use
    expect(pg.locator("#wifiUseMsg")).to_have_text("Wi-Fi moved to the Built-in MediaTek.")
    pg.keyboard.press("Control+4")
    expect(pg.locator("#trafficTitle")).to_have_text("Traffic on Built-in MediaTek", timeout=4000)  # the adapter in use leads


def test_traffic_polling_stops_while_the_window_is_hidden(open_page):
    pg = traffic_page(open_page)
    pg.evaluate("""window.n = 0; const t = mockApi.traffic;
        mockApi.traffic = (...x) => { window.n++; return t(...x); };
        mockApi.is_visible = async () => ({ ok: true, data: false });""")
    pg.wait_for_timeout(2600)
    assert pg.evaluate("window.n") == 0
    pg.evaluate("mockApi.is_visible = async () => ({ ok: true, data: true })")
    pg.wait_for_timeout(2200)
    assert pg.evaluate("window.n") >= 1


def test_rate_text_in_the_page_matches_the_one_in_the_tray_tooltip(open_page):
    import traffic
    pg = open_page()
    for unit in ("bytes", "bits"):
        for v in (0, 999, 40_000, 512_000, 999_400, 999_600, 4_200_000, 33_600_000, 120_000_000):
            assert pg.evaluate("([v, u]) => fmtRate(v, u)", [v, unit]) == traffic.fmt_rate(v, unit), (v, unit)
    assert [pg.evaluate("n => fmtBytes(n)", n) for n in (0, 400_000, 1_234_567, 3_860_000_000)] == ["0 KB", "400 KB", "1.2 MB", "3.86 GB"]


def test_traffic_page_is_square_uses_five_sizes_and_its_only_shadow_is_the_unit_switch(open_page):
    pg = traffic_page(open_page)
    expect(pg.locator("#traf .line")).to_have_count(2, timeout=4000)
    assert pg.evaluate(ROUND) == []
    assert set(pg.evaluate(TEXT_SIZES)) <= SIZES, pg.evaluate(TEXT_SIZES)
    assert re.match(r"^rgb\(\d+, \d+, \d+\) 4px 4px 0px 0px$", shadow(pg, "#trafficUnit"))
    shadows = pg.evaluate("""() => [...document.querySelectorAll('#traffic *')].filter(e => !e.closest('svg') && getComputedStyle(e).boxShadow !== 'none')
        .map(e => e.id || e.className)""")
    assert shadows == ["trafficUnit"], shadows  # readouts, cards and rows are flat: depth means pressable
    assert pg.evaluate("document.querySelector('#trafficUnit').classList.contains('seg')")
    box = pg.locator('#trafficUnit button[data-k="bits"]').bounding_box()  # the one press: it sinks onto its shadow
    pg.mouse.move(box["x"] + 8, box["y"] + 8)
    pg.mouse.down()
    pg.wait_for_timeout(300)
    assert "0px 0px 0px" in shadow(pg, "#trafficUnit")
    pg.mouse.up()


# ---- the dongle's driver: panel, one button, five steps ----
DRIVER_FAIL = "The downloaded file isn't the expected driver (its checksum differs), so it was not used. Nothing was installed."


def test_driver_panel_is_hidden_while_the_dongle_has_its_driver(open_page):
    pg = open_page()
    expect(pg.locator("#driver")).to_be_hidden()
    expect(pg.locator("#dongle")).to_have_text("Dongle connected")


def test_driver_panel_offers_one_button_when_the_dongle_has_no_driver(open_page):
    pg = open_page("window.MOCK_DRIVER = 'missing';")
    expect(pg.locator("#driver")).to_be_visible()
    expect(pg.locator("#driverTitle")).to_have_text("Unigen dongle driver not installed")
    expect(pg.locator("#driverGo")).to_have_text("Download & install")
    expect(pg.locator("#driverGo")).to_be_enabled()
    expect(pg.locator("#driverSteps")).to_be_hidden()  # no bar until the click
    expect(pg.locator("#dongle")).to_have_text("Dongle driver not installed. Install it on the Wi-Fi page.")
    expect(pg.locator("#dongle")).to_have_attribute("data-state", "no_driver")
    expect(wifi_use(pg, "unigen")).to_be_disabled()
    expect(wifi_use(pg, "unigen")).to_have_attribute("title", "Install the dongle's driver first.")


def test_nothing_installs_until_the_click(open_page):
    pg = open_page("window.MOCK_DRIVER = 'missing'; window.MOCK_LOG = [];")
    pg.wait_for_timeout(500)
    assert "install_driver" not in pg.evaluate("window.MOCK_LOG")
    pg.locator("#driverGo").click()
    expect(pg.locator("#driverSteps")).to_have_attribute("data-bar", "done", timeout=6000)
    assert pg.evaluate("window.MOCK_LOG").count("install_driver") == 1


def test_driver_install_shows_five_steps_then_the_wifi_adapter(open_page):
    pg = open_page("window.MOCK_DRIVER = 'missing'; window.MOCK_HOLD_STEP = 3;")
    pg.locator("#driverGo").click()
    expect(blocks(pg, "driverSteps")).to_have_count(5)  # download, verify, unpack, install, check
    expect(pg.locator("#driverSteps .steps-title")).to_have_text("Installing the driver")
    expect(pg.locator("#driverSteps .steps-count")).to_contain_text("3/5 · ")
    expect(pg.locator("#driverSteps .steps-label")).to_have_text("Unpacking")
    assert states(pg, "driverSteps") == ["done", "done", "current", "empty", "empty"]
    expect(pg.locator("#driverGo")).to_be_disabled()
    expect(pg.locator("#driverCancel")).to_be_visible()  # until Windows starts installing
    assert pg.evaluate("getComputedStyle(document.querySelector('#driverSteps')).getPropertyValue('--accent')").strip().lower() == "#9085e9"  # --uni
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#driverSteps .steps-fold-t")).to_have_text("Driver installed. The dongle's Wi-Fi is ready", timeout=6000)
    expect(pg.locator("#driverTitle")).to_have_text("Unigen dongle driver installed")
    expect(pg.locator("#driver")).to_have_attribute("data-s", "done")
    expect(pg.locator("#dongle")).to_have_text("Dongle connected")  # the page reloaded: the adapter exists
    expect(wifi_use(pg, "unigen")).to_be_enabled()
    expect(pg.locator(".adapter").filter(has_text="Unigen dongle")).to_be_visible()
    expect(pg.locator("#driver")).to_be_hidden(timeout=9000)  # lingers a few seconds, then goes


def test_driver_download_shows_its_running_figures_and_cancel_stops_it(open_page):
    pg = open_page("window.MOCK_DRIVER = 'missing'; window.MOCK_FAST = false;")
    pg.locator("#driverGo").click()
    expect(pg.locator("#driverSteps .steps-label")).to_have_text(re.compile(r"Downloading \d\.\d of 3\.3 MB"))
    pg.locator("#driverCancel").click()
    expect(pg.locator("#driverSteps")).to_have_attribute("data-bar", "fail", timeout=4000)
    expect(pg.locator("#driverMsg")).to_have_text("Cancelled. Nothing was installed.")
    expect(pg.locator("#driverTitle")).to_have_text("Unigen dongle driver not installed")  # still offered
    expect(pg.locator("#driverGo")).to_be_enabled()


def test_driver_failure_names_the_step_and_try_again_works(open_page):
    pg = open_page(f'window.MOCK_DRIVER = "missing"; window.MOCK_DRIVER_FAIL = "{DRIVER_FAIL}"; window.MOCK_FAIL_STEP = 2;')
    pg.locator("#driverGo").click()
    expect(pg.locator("#driverSteps .retry")).to_be_visible(timeout=6000)
    assert states(pg, "driverSteps") == ["done", "failed", "empty", "empty", "empty"]
    expect(pg.locator("#driverSteps .steps-count")).to_have_text("2/5 · failed")
    expect(pg.locator("#driverSteps .steps-label")).to_have_text("Verifying")
    expect(pg.locator("#driverMsg")).to_have_text(DRIVER_FAIL)
    expect(pg.locator("#driverMsg")).to_have_class("msg err")
    expect(pg.locator("#driverCancel")).to_be_hidden()
    expect(pg.locator("#driverGo")).to_be_enabled()
    pg.evaluate("window.MOCK_DRIVER_FAIL = null")
    pg.locator("#driverSteps .retry").click()
    expect(pg.locator("#driverSteps .steps-fold-t")).to_have_text("Driver installed. The dongle's Wi-Fi is ready", timeout=6000)


def test_driver_install_needs_admin(open_page):
    pg = open_page("window.MOCK_DRIVER = 'missing'; window.MOCK_ADMIN = false;")
    expect(pg.locator("#driverGo")).to_be_disabled()
    expect(pg.locator("#driverGo")).to_have_attribute("title", "Installing the driver needs administrator rights.")


def test_driver_panel_is_square_and_uses_the_shared_bar(open_page):
    pg = open_page("window.MOCK_DRIVER = 'missing';")
    css = pg.evaluate("""() => { const c = getComputedStyle(document.querySelector('#driver'));
      return [c.borderTopWidth, c.borderRadius, c.boxShadow, c.borderTopColor] }""")
    assert css[0] == "2px" and css[1] == "0px" and css[2] == "none"  # depth means pressable: the panel has no shadow, the button has
    assert pg.evaluate("getComputedStyle(document.querySelector('#driverGo')).boxShadow") != "none"
