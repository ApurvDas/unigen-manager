import re
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "ui"
HELPERS = ["function call(", "function slide(", "function swap(", "async function busy(", "function arrive(",
           "function setText(", "function setMsg(", "function scramble(", "function pop(", "function relayout(",
           "function removeEl(", "function addEl(", "function buildSeg(", "function markSeg(", "function enableSeg(", "function renderDongle(",
           "function buildProgress(", "function renderStep(", "function failProgress(", "function clearProgress(", "function noteBar(",
           "const COLOR =", "function rateParts(", "function fmtRate(", "function fmtBytes(", "function buildUnitSeg(", "function markUnit(",
           "async function pickUnit(", "function trafficChart("]


def test_index_uses_shared_files():
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="shared.css">' in html
    assert '<script src="shared.js"></script>' in html
    assert "--panel:" not in html  # tokens live only in shared.css
    assert not any(h in html for h in HELPERS)  # helpers live only in shared.js
    assert "renderStep(" in html and "buildProgress(" in html  # and the page uses the shared progress bar


def test_shared_files_define_everything():
    css = (UI / "shared.css").read_text(encoding="utf-8")
    js = (UI / "shared.js").read_text(encoding="utf-8")
    assert "--panel: #16202B" in css and "--uni: #9085e9" in css and ".btn.primary" in css
    assert all(h in js for h in HELPERS)
    # every timing of the switch area is a named constant, and the bar styles are shared by both windows
    for name in ("PRESS_MS", "RELEASE_MS", "SLIDE_MS", "ENTER_MS", "STAGGER_MS", "SWEEP_MS", "SNAP_MS", "FLASH_MS", "FOLD_MS",
                 "LINGER_MS", "SHAKE_MS", "SWAP_MS", "POP_MS", "ROW_Y", "STAGGER_CAP_MS",
                 "TRAFFIC_MS", "TRAFFIC_N", "SCROLL_MS", "AXIS_EASE", "AXIS_FLOOR"):
        assert f"const {name}" in js or f", {name} =" in js
    assert ".steps.compact" in css and ".blk[data-s=\"failed\"]" in css and "border-radius: 0" in css


def test_shared_css_is_one_square_system_with_five_type_sizes():
    css = (UI / "shared.css").read_text(encoding="utf-8")
    assert "scale(" not in (UI / "shared.js").read_text(encoding="utf-8").split("// press:")[1].split("// slide:")[0]  # the press sinks, it doesn't shrink
    assert "blur(" not in (UI / "shared.js").read_text(encoding="utf-8")  # a label swap has no blur
    sizes = set(re.findall(r"--t-\w+: (\d+)px", css))
    assert sizes == {"11", "12", "14", "24", "48"}
    assert "box-shadow: 0 " not in css and "rgba(0, 0, 0" not in css  # no soft shadows


def test_widget_uses_shared_files():
    html = (UI / "widget.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="shared.css">' in html and '<script src="shared.js"></script>' in html
    assert "--panel:" not in html and not any(h in html for h in HELPERS)


def test_widget_reports_its_height_while_hidden_too():
    """The page lays out before the first open; gating the fit on `shown` left the window at its 480 px default and
    cut off the sections below (Traffic), since nothing changed size once it opened."""
    html = (UI / "widget.html").read_text(encoding="utf-8")
    observer = html.split("new ResizeObserver(")[1].split(".observe(W)")[0]
    assert 'call("widget_fit"' in observer and "shown" not in observer


def test_traffic_timings_live_in_shared_js_not_in_the_pages():
    js = (UI / "shared.js").read_text(encoding="utf-8")
    assert "const TRAFFIC_MS = 1000" in js and "SCROLL_MS = TRAFFIC_MS" in js  # the chart scrolls one step per tick
    for page in ("index.html", "widget.html"):
        html = (UI / page).read_text(encoding="utf-8")
        assert "}, TRAFFIC_MS)" in html  # polled at the shared interval, not a number of its own
        assert not re.search(r"loadTraffic\(\)[^;\n]*\}, \d+\)", html)
        assert "function trafficChart(" not in html and "nice =" not in html and "endMark =" not in html  # shared, not copied
