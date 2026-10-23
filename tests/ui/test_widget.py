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

    def _open(hooks="", ads=2, **ctx):
        pg = browser.new_page(viewport={"width": 1000, "height": 760}, **ctx)
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.add_init_script("window.MOCK_FAST = true;" + hooks)
        pg.goto(base_url)
        pg.locator("#chevron").click()
        pg.locator("#trayIcon").click()
        expect(pg.locator("#w")).to_be_visible()
        expect(pg.locator(".ad")).to_have_count(ads)
        pages.append(pg)
        return pg

    yield _open
    for pg in pages:
        assert pg.errors == []
        pg.close()


def ad(pg, key):
    return pg.locator(f'.ad[data-k="{key}"]')


def wifi_use(pg, key):
    return pg.locator(f'#wifiUse button[data-k="{key}"]')


def bt_use(pg, key):
    return pg.locator(f'#btUse button[data-k="{key}"]')


def test_opens_from_tray_and_shows_live_status(widget):
    pg = widget()
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("HOME-5G")
    expect(pg.locator('#wifiUse button[aria-checked="true"]')).to_have_text("Dongle")
    expect(pg.locator('#btUse button[aria-checked="true"]')).to_have_text("Dongle")
    expect(pg.locator("#wifiUseLbl")).to_have_text("Wi-Fi")
    expect(pg.locator("#btUseLbl")).to_have_text("Bluetooth")
    expect(pg.locator("#nets .net")).to_have_count(2)  # saved networks in range on the Unigen dongle
    expect(pg.locator("#btVer")).to_have_text("Bluetooth 5.4")
    expect(pg.locator("#btDev")).to_have_text("Den Beats Pill · 90%")
    pg.mouse.click(100, 100)
    expect(pg.locator("#w")).to_be_hidden()  # like Windows flyouts: clicking elsewhere closes it


def test_close_button_hides_the_widget(widget):
    pg = widget()
    pg.locator("#closeWidget").click()
    expect(pg.locator("#w")).to_be_hidden()


def test_widget_wifi_switch(widget):
    pg = widget()
    expect(ad(pg, "builtin").locator(".ssid")).to_have_text("Off")
    wifi_use(pg, "builtin").click()
    expect(pg.locator("#wifiMsg")).to_have_text("Wi-Fi moved to the Built-in MediaTek.")
    expect(wifi_use(pg, "builtin")).to_have_attribute("aria-checked", "true")
    expect(ad(pg, "builtin").locator(".ssid")).to_have_text("HOME-5G")
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("Off")
    expect(pg.locator("#btVer")).to_have_text("Bluetooth 5.4")  # Bluetooth did not move with Wi-Fi
    expect(bt_use(pg, "unigen")).to_have_attribute("aria-checked", "true")


def test_widget_bluetooth_switch(widget):
    pg = widget()
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btMsg")).to_have_text("Bluetooth moved to the Built-in MediaTek.")
    expect(bt_use(pg, "builtin")).to_have_attribute("aria-checked", "true")
    expect(pg.locator("#btVer")).to_have_text("Bluetooth 5.2")
    expect(wifi_use(pg, "unigen")).to_have_attribute("aria-checked", "true")  # Wi-Fi did not move with Bluetooth
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("HOME-5G")
    expect(ad(pg, "builtin").locator(".ssid")).to_have_text("Off")


def test_widget_shows_each_step(widget):
    pg = widget("window.MOCK_HOLD_STEP = 3;")  # the move waits at step 3 until released
    wifi_use(pg, "builtin").click()
    expect(pg.locator("#wifiMsg")).to_have_text("Finding HOME-5G…")
    expect(pg.locator("#wifiUse button").first).to_be_disabled()
    expect(pg.locator("#btUse button").first).to_be_disabled()  # one lock: Bluetooth waits too
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#wifiMsg")).to_have_text("Wi-Fi moved to the Built-in MediaTek.", timeout=5000)
    expect(pg.locator("#wifiUse button").first).to_be_enabled()
    pg.evaluate("window.MOCK_HOLD_STEP = 2")
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btMsg")).to_have_text("Turning off the Unigen dongle radio…")
    expect(pg.locator("#btUse button").first).to_be_disabled()  # until the move ends
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#btMsg")).to_have_text("Bluetooth moved to the Built-in MediaTek.", timeout=6000)
    expect(pg.locator("#btUse button").first).to_be_enabled()


def test_widget_wifi_failure_puts_the_switch_back(widget):
    msg = "Couldn't finish switching to the Built-in MediaTek. You're still on the Unigen dongle."
    pg = widget(f'window.MOCK_FAIL = {{ switch_wifi: "{msg}" }};')
    wifi_use(pg, "builtin").click()
    expect(pg.locator("#wifiMsg")).to_have_text(msg)
    expect(pg.locator('#wifiUse button[aria-checked="true"]')).to_have_text("Dongle")


def test_widget_bluetooth_failure_puts_the_switch_back(widget):
    msg = "A switch is still finishing. Bluetooth can take up to a minute; try again in a moment."
    pg = widget(f'window.MOCK_FAIL = {{ switch_bt: "{msg}" }};')
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btMsg")).to_have_text(msg)
    expect(pg.locator('#btUse button[aria-checked="true"]')).to_have_text("Dongle")
    late = "Bluetooth couldn't move and stays on the Unigen dongle. Switch again to retry."
    pg = widget(f'window.MOCK_BT_FAIL = "{late}";')
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btMsg")).to_have_text(late)
    expect(pg.locator('#btUse button[aria-checked="true"]')).to_have_text("Dongle")  # what Windows really has
    expect(pg.locator("#btUse button").first).to_be_enabled()


def test_widget_switches_need_admin(widget):
    pg = widget("window.MOCK_ADMIN = false;")
    for seg in ("#wifiUse", "#btUse"):
        expect(pg.locator(f"{seg} button").first).to_be_disabled()
        expect(pg.locator(seg)).to_have_attribute("title", "Switching adapters needs administrator rights.")


def test_widget_using_changed_event_reloads(widget):
    pg = widget()
    pg.evaluate("mockApi._setUsing('builtin'); window.onUsingChanged()")
    expect(wifi_use(pg, "builtin")).to_have_attribute("aria-checked", "true")
    expect(bt_use(pg, "builtin")).to_have_attribute("aria-checked", "true")
    expect(pg.locator("#btVer")).to_have_text("Bluetooth 5.2")
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("Off")


def test_disconnect_and_connect_saved(widget):
    pg = widget()
    home = pg.locator("#nets .net").filter(has=pg.get_by_text("HOME-5G", exact=True))
    home.locator("button").click()
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("Not connected")
    expect(home.locator("button .label")).to_have_text("Connect")
    home.locator("button").click()
    expect(ad(pg, "unigen").locator(".ssid")).to_have_text("HOME-5G")


def test_bluetooth_row_has_no_switch_button(widget):
    pg = widget()
    assert pg.locator("#btSwitch").count() == 0


def test_speed_test_sparkline(widget):
    pg = widget()
    pg.locator("#run").click()
    expect(pg.locator("#run .label")).to_have_text("Run test", timeout=10000)
    expect(pg.locator("#spark .line")).to_have_count(2)  # download and upload segments
    assert pg.locator("#dn").inner_text() not in ("", "–")


def test_confirmations_fade_errors_stay(widget):
    pg = widget()
    wifi_use(pg, "builtin").click()
    expect(pg.locator("#wifiMsg")).not_to_be_empty()
    expect(pg.locator("#wifiMsg")).to_be_empty(timeout=6000)


def test_widget_bluetooth_power(widget):
    pg = widget()
    sw = pg.locator("#btPower")
    expect(sw).to_have_attribute("aria-checked", "true")
    sw.click()
    expect(sw).to_have_attribute("aria-checked", "false")
    expect(pg.locator("#btDev")).to_have_text("Bluetooth is off")
    sw.click()
    expect(sw).to_have_attribute("aria-checked", "true")


def test_widget_shows_connected_device_battery(widget):
    pg = widget()
    expect(pg.locator("#btDev")).to_have_text("Den Beats Pill · 90%")


def test_widget_dongle_status_line(widget):
    pg = widget()
    expect(pg.locator("#dongle")).to_have_text("Dongle connected")
    expect(pg.locator("#dongle")).to_have_attribute("data-state", "connected")
    expect(wifi_use(pg, "unigen")).to_be_enabled()
    expect(bt_use(pg, "unigen")).to_be_enabled()


def test_widget_unplugged_dongle_disables_its_buttons(widget):
    pg = widget("window.MOCK_UNPLUG = 'unigen';", ads=1)
    expect(pg.locator("#dongle")).to_have_text("Dongle not plugged in")
    for use in (wifi_use, bt_use):
        expect(use(pg, "unigen")).to_be_disabled()
        expect(use(pg, "unigen")).to_have_attribute("title", "Plug in the dongle.")
        expect(use(pg, "builtin")).to_be_enabled()
        expect(use(pg, "builtin")).to_have_attribute("aria-checked", "true")


def test_widget_dongle_not_responding(widget):
    pg = widget("window.MOCK_DONGLE = 'not_responding';")
    expect(pg.locator("#dongle")).to_have_text("Dongle not responding. Unplug it and plug it back in.")
    expect(wifi_use(pg, "unigen")).to_have_attribute("title", "Unplug the dongle and plug it back in.")


def test_widget_dongle_status_follows_the_watchdog_and_looks_again(widget):
    pg = widget()
    pg.evaluate("mockApi._setDongle('unplugged'); window.onUsingChanged()")
    expect(pg.locator("#dongle")).to_have_text("Dongle not plugged in")
    expect(bt_use(pg, "unigen")).to_be_disabled()
    pg.evaluate("mockApi._setDongle('connected')")
    expect(pg.locator("#dongle")).to_have_text("Dongle connected", timeout=8000)
    expect(bt_use(pg, "unigen")).to_be_enabled()


# ---- the compact progress bars and the Bluetooth lock-out ----
def states(pg, bar):
    return pg.eval_on_selector_all(f"#{bar} .blk", "bs => bs.map(b => b.dataset.s)")


def test_widget_bar_is_compact_one_line_under_the_switch(widget):
    pg = widget("window.MOCK_HOLD_STEP = 2;")
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btSteps .blk")).to_have_count(4)
    expect(pg.locator("#btSteps .steps-count")).to_contain_text("2/4 · ")
    expect(pg.locator("#btSteps .steps-label")).to_have_text("Turning off the Unigen dongle radio")
    expect(pg.locator("#btSteps .steps-title")).to_be_hidden()  # the title is for the main window
    assert states(pg, "btSteps") == ["done", "current", "empty", "empty"]
    assert pg.evaluate("getComputedStyle(document.querySelector('#btSteps .blk')).height") == "6px"
    count, label = (pg.locator(f"#btSteps .{c}").bounding_box() for c in ("steps-count", "steps-label"))
    assert abs(count["y"] - label["y"]) < 4 and count["x"] < label["x"]  # the count and the name share one line
    box = pg.locator("#w").bounding_box()
    assert pg.locator("#btSteps").bounding_box()["x"] >= box["x"] and pg.locator("#btSteps").bounding_box()["width"] <= box["width"]
    below = pg.locator(".bt").bounding_box()["y"]
    assert below >= pg.locator("#btSteps").bounding_box()["y"] + pg.locator("#btSteps").bounding_box()["height"]  # nothing overlaps
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#btSteps .steps-fold-t")).to_have_text("Bluetooth moved to the Built-in MediaTek", timeout=6000)
    expect(pg.locator("#btSteps .steps-body")).to_be_hidden()  # folded into one line
    expect(pg.locator("#btSteps")).to_be_hidden(timeout=9000)


def test_widget_wifi_bar_and_skipped_bluetooth_steps(widget):
    pg = widget("window.MOCK_HOLD_STEP = 3;")
    wifi_use(pg, "builtin").click()
    expect(pg.locator("#wifiSteps .blk")).to_have_count(5)
    assert states(pg, "wifiSteps") == ["done", "done", "current", "empty", "empty"]
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#wifiSteps .steps-fold")).to_be_visible(timeout=5000)
    pg.evaluate("mockApi._setConnected('BT-beats', false)")  # nothing connected: nothing to disconnect or reconnect
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btSteps .steps-count")).to_contain_text("3/4", timeout=6000)


def test_widget_power_switch_is_off_while_bluetooth_moves(widget):
    pg = widget("window.MOCK_HOLD_STEP = 2;")
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btSteps .steps-count")).to_contain_text("2/4")
    expect(pg.locator("#btPower")).to_be_disabled()
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#btSteps .steps-fold")).to_be_visible(timeout=6000)
    expect(pg.locator("#btPower")).to_be_enabled()


def test_widget_failed_move_shows_the_block_and_try_again(widget):
    late = "Windows didn't turn off the Unigen dongle radio, usually because audio is still playing through it."
    pg = widget(f'window.MOCK_BT_FAIL = "{late}"; window.MOCK_FAIL_STEP = 2;')
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btSteps .retry")).to_be_visible(timeout=6000)
    assert states(pg, "btSteps") == ["done", "failed", "empty", "empty"]
    expect(pg.locator("#btMsg")).to_have_text(late)
    expect(pg.locator("#btMsg")).to_have_class("msg err")
    expect(bt_use(pg, "unigen")).to_have_attribute("aria-checked", "true")
    pg.evaluate("window.MOCK_BT_FAIL = null")
    pg.locator("#btSteps .retry").click()
    expect(pg.locator("#btSteps .steps-fold-t")).to_have_text("Bluetooth moved to the Built-in MediaTek", timeout=6000)
    expect(bt_use(pg, "builtin")).to_have_attribute("aria-checked", "true")


def test_widget_switch_stays_on_the_asked_adapter_while_polling(widget):
    pg = widget("window.MOCK_HOLD_STEP = 2;")
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btSteps .steps-count")).to_contain_text("2/4")
    pg.evaluate("poll(); loadBt()")  # the widget polls every few seconds: the switch must not slide back to the old radio
    pg.wait_for_timeout(600)
    expect(bt_use(pg, "builtin")).to_have_attribute("aria-checked", "true")
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#btSteps .steps-fold")).to_be_visible(timeout=6000)


def test_widget_pressing_a_switch_while_a_move_runs_says_so(widget):
    pg = widget()
    pg.evaluate("window.onSwitchStep({ kind: 'wifi', text: 'Finding HOME-5G…', done: false, error: false, step: 3, of: 5, label: 'Finding HOME-5G' })")
    expect(pg.locator("#wifiSteps .steps-count")).to_contain_text("3/5")  # a move started elsewhere shows its bar here
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btMsg")).to_have_text("Already moving Wi-Fi · 3/5")
    expect(pg.locator("#btMsg")).not_to_have_class("msg err")
    expect(bt_use(pg, "unigen")).to_have_attribute("aria-checked", "true")  # nothing was asked of the backend


def test_widget_reduced_motion_has_no_hatch_or_sweep(widget):
    pg = widget("window.MOCK_HOLD_STEP = 2;", reduced_motion="reduce")
    bt_use(pg, "builtin").click()
    expect(pg.locator("#btSteps .steps-count")).to_contain_text("2/4")
    cur = "#btSteps .blk[data-s='current'] b"
    assert pg.evaluate(f"getComputedStyle(document.querySelector(\"{cur}\"), '::after').animationName") == "none"
    assert pg.evaluate(f"document.querySelector(\"{cur}\").style.transform") == ""
    pg.evaluate("mockApi._resume()")
    expect(pg.locator("#btSteps .steps-fold")).to_be_visible(timeout=6000)


# ---- the design system, compact ----
def test_widget_is_square_with_three_pixel_shadows_and_five_type_sizes(widget):
    pg = widget()
    round_ = pg.evaluate("""() => [...document.querySelectorAll('#w, #w *')].filter(e => !e.closest('svg') &&
        ['TopLeft', 'TopRight', 'BottomLeft', 'BottomRight'].some(c => getComputedStyle(e)['border' + c + 'Radius'] !== '0px')).map(e => e.className)""")
    assert round_ == []
    sizes = pg.evaluate("""() => [...new Set([...document.querySelectorAll('#w *')].filter(e => getComputedStyle(e).display !== 'none' &&
        [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())).map(e => getComputedStyle(e).fontSize))]""")
    assert set(sizes) <= {"11px", "12px", "14px", "24px", "48px"}, sizes
    shadow = lambda sel: pg.evaluate(f"getComputedStyle(document.querySelector('{sel}')).boxShadow")
    for sel in ("#run", "#openApp", "#nets .btn", "#btPower"):
        assert "3px 3px 0px" in shadow(sel), sel  # 3px offsets in the widget, 4px in the window
    assert "3px 3px 0px" in shadow("#wifiUse") and "rgb(144, 133, 233)" in shadow("#wifiUse")
    sections = pg.eval_on_selector_all(".sec", "ss => ss.map(s => getComputedStyle(s).borderTopWidth + ' ' + getComputedStyle(s).boxShadow)")
    assert set(sections) == {"2px none"}  # every section a square 2px panel; static panels have no shadow


def test_widget_signal_bars_are_square_blocks(widget):
    pg = widget()
    assert pg.eval_on_selector_all(".ad:first-child .bars i.lit", "b => b.length") == 4
    assert pg.evaluate("[...document.querySelectorAll('.bars i')].every(b => getComputedStyle(b).borderTopLeftRadius === '0px')")
    assert pg.evaluate("getComputedStyle(document.querySelector('.ad .dot')).borderTopLeftRadius") == "0px"  # the status pip is square


def test_widget_press_sinks_onto_the_shadow(widget):
    pg = widget()
    box = pg.locator("#run").bounding_box()
    pg.mouse.move(box["x"] + 8, box["y"] + 8)
    pg.mouse.down()
    pg.wait_for_timeout(300)
    assert "0px 0px 0px" in pg.evaluate("getComputedStyle(document.querySelector('#run')).boxShadow")
    pg.mouse.up()
    pg.wait_for_timeout(900)
    assert "3px 3px 0px" in pg.evaluate("getComputedStyle(document.querySelector('#run')).boxShadow")


# ---- traffic ----
def test_widget_traffic_section_shows_the_live_rates_and_a_sparkline(widget):
    pg = widget()
    expect(pg.locator(".sec h2").filter(has_text="Traffic")).to_be_visible()
    pg.evaluate("mockApi._setRate(4200000, 300000)")
    expect(pg.locator("#trDn")).to_have_text("4.2", timeout=4000)
    expect(pg.locator("#trDnU")).to_have_text("MB/s")
    expect(pg.locator("#trUp")).to_have_text("300")
    expect(pg.locator("#trUpU")).to_have_text("KB/s")
    expect(pg.locator("#tspark .line")).to_have_count(2)
    assert pg.evaluate("[...document.querySelectorAll('#tspark .line')].map(l => l.getAttribute('d').match(/[ML]/g).length)") == [60, 60]
    assert pg.evaluate("[...document.querySelectorAll('#tspark .line')].map(l => l.getAttribute('stroke'))") == ["var(--uni)", "var(--ink)"]
    assert pg.evaluate("document.querySelector('#w').getBoundingClientRect().height") <= 900  # api.widget_fit never asks for more


def test_widget_traffic_click_switches_the_unit_and_a_push_from_the_other_window_follows(widget):
    pg = widget()
    pg.evaluate("mockApi._setRate(4200000, 300000)")
    expect(pg.locator("#trDn")).to_have_text("4.2", timeout=4000)
    pg.locator("#trUp").click()  # either number switches it
    expect(pg.locator("#trDn")).to_have_text("33.6")
    expect(pg.locator("#trDnU")).to_have_text("Mbps")
    expect(pg.locator("#trUp")).to_have_text("2.4")
    pg.locator("#trDn").click()
    expect(pg.locator("#trDnU")).to_have_text("MB/s")
    pg.evaluate("window.onTrafficUnit('bits')")  # the main window changed it: Python pushes to both
    expect(pg.locator("#trUpU")).to_have_text("Mbps")


def test_widget_traffic_empty_state(widget):
    pg = widget("window.MOCK_TRAFFIC = 'none';")
    expect(pg.locator("#trEmpty")).to_have_text("No Wi-Fi adapter is on")
    expect(pg.locator("#tspark")).to_be_hidden()
    expect(pg.locator("#trDn")).to_have_text("–")


def test_widget_traffic_measuring_state(widget):
    pg = widget("window.MOCK_TRAFFIC = 'measuring';")
    expect(pg.locator("#trEmpty")).to_have_text("Measuring…")
    expect(pg.locator("#tspark")).to_be_hidden()


def test_widget_traffic_numbers_are_a_pressable_link_without_a_shadow(widget):
    pg = widget()
    expect(pg.locator("#trNums")).to_have_attribute("title", "Switch between MB/s and Mbps")
    assert pg.evaluate("getComputedStyle(document.querySelector('#trNums')).boxShadow") == "none"
    assert pg.evaluate("document.querySelector('#trNums').classList.contains('link')")  # pressing it sinks it like every pressable


def test_widget_dongle_without_driver_says_so_and_shows_the_install_line(widget):
    pg = widget("window.MOCK_DRIVER = 'missing';", ads=1)
    expect(pg.locator("#dongle")).to_have_text("Dongle driver not installed. Install it on the Wi-Fi page.")
    expect(wifi_use(pg, "unigen")).to_be_disabled()
    expect(wifi_use(pg, "unigen")).to_have_attribute("title", "Install the dongle's driver first.")
    pg.evaluate("mockApi.install_driver()")  # started in the main window: the widget follows on its message line
    expect(pg.locator("#wifiMsg")).to_have_text("Driver installed. The dongle's Wi-Fi is ready.", timeout=6000)
    expect(pg.locator("#dongle")).to_have_text("Dongle connected")
    expect(pg.locator(".ad")).to_have_count(2)


# ---- merge connections ----
def test_widget_merge_switch_turns_merge_on_and_off_and_shows_a_badge(widget):
    pg = widget()
    pg.evaluate("""window.__calls = []; const f = mockApi.set_merge; mockApi.set_merge = (...a) => { window.__calls.push(a); return f(...a); }; null;""")
    expect(pg.locator("#mergeSw")).to_have_attribute("aria-checked", "false")
    expect(pg.locator("#mergeSw")).to_have_attribute("aria-label", "Merge connections")
    expect(pg.locator("#mergeBadge")).to_be_hidden()
    pg.locator("#mergeSw").click()
    expect(pg.locator("#mergeSw")).to_have_attribute("aria-checked", "true")
    expect(pg.locator("#mergeBadge")).to_have_text("Merged")
    assert pg.evaluate("window.__calls") == [[True]]
    pg.locator("#mergeSw").click()
    expect(pg.locator("#mergeSw")).to_have_attribute("aria-checked", "false")
    expect(pg.locator("#mergeBadge")).to_be_hidden()
    assert pg.evaluate("window.__calls") == [[True], [False]]


def test_widget_shows_merge_that_is_already_on_and_follows_a_push_from_the_other_window(widget):
    pg = widget("window.MOCK_MERGE = true;")
    expect(pg.locator("#mergeSw")).to_have_attribute("aria-checked", "true")
    expect(pg.locator("#mergeBadge")).to_have_text("Merged")
    pg.evaluate("mockApi.set_merge(false)")  # switched in the main window: Python then pushes onMerge to both
    expect(pg.locator("#mergeSw")).to_have_attribute("aria-checked", "false")
    expect(pg.locator("#mergeBadge")).to_be_hidden()


def test_widget_merge_switch_failure_goes_back_with_the_reason(widget):
    pg = widget('window.MOCK_FAIL = { set_merge: "Couldn\'t turn the Built-in MediaTek on." };')
    pg.locator("#mergeSw").click()
    expect(pg.locator("#mergeMsg")).to_have_text("Couldn't turn the Built-in MediaTek on.")
    expect(pg.locator("#mergeSw")).to_have_attribute("aria-checked", "false")
    expect(pg.locator("#mergeSw")).to_be_enabled()


def test_widget_merge_switch_needs_admin(widget):
    pg = widget("window.MOCK_ADMIN = false;")
    expect(pg.locator("#mergeSw")).to_be_disabled()
    expect(pg.locator("#mergeSw")).to_have_attribute("title", "Merging connections needs administrator rights.")
