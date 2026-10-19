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
    expect(pg.locator("#wifiUseMsg")).to_have_text("The Unigen dongle is off.")
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
    pg = open_page("window.MOCK_FAST = false;")  # real 300 ms steps
    wifi_use(pg, "builtin").click()
    expect(pg.locator("#wifiUseMsg")).to_have_text("Turning on the Built-in MediaTek…")
    expect(pg.locator("#wifiUse button").first).to_be_disabled()
    expect(pg.locator("#wifiUseMsg")).to_have_text("Connecting to HOME-5G…", timeout=3000)
    expect(pg.locator("#wifiUseMsg")).to_have_text("Done. Using the Built-in MediaTek.", timeout=5000)
    expect(pg.locator("#wifiUse button").first).to_be_enabled()  # Wi-Fi works: no waiting for the old one to go off
    expect(pg.locator("#wifiUseMsg")).to_have_text("The Unigen dongle is off.", timeout=3000)


def test_bluetooth_switch_on_the_bluetooth_tab(open_page):
    pg = open_page("window.MOCK_FAST = false;")
    pg.keyboard.press("Control+2")
    expect(pg.locator("#btUse button")).to_have_text(["Dongle", "Built-in"])
    expect(bt_use(pg, "unigen")).to_have_attribute("aria-checked", "true")
    expect(pg.locator("#btRadio")).to_have_text("Unigen dongle")
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btUseMsg")).to_have_text("Moving Bluetooth to the Built-in MediaTek. This can take up to a minute.")
    expect(pg.locator("#btUse button").first).to_be_disabled()  # until the move ends
    expect(pg.locator("#wifiUse button").first).to_be_disabled()  # one lock: Wi-Fi waits too
    expect(pg.locator("#btUseMsg")).to_have_text("Bluetooth moved to the Built-in MediaTek.", timeout=3000)
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
