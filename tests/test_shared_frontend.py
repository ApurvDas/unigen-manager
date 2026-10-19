import re
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "ui"
HELPERS = ["function call(", "function slide(", "function swap(", "async function busy(", "function arrive(",
           "function setText(", "function setMsg(", "function scramble(", "function pop(", "function relayout(",
           "function removeEl(", "function addEl(", "function buildSeg(", "function markSeg(", "function enableSeg(", "function renderDongle(",
           "function buildProgress(", "function renderStep(", "function failProgress(", "function clearProgress(", "function noteBar(",
           "const COLOR ="]


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
                 "LINGER_MS", "SHAKE_MS", "SWAP_MS", "POP_MS", "ROW_Y", "STAGGER_CAP_MS"):
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
