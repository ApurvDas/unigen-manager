from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "ui"
HELPERS = ["function call(", "function slide(", "function swap(", "async function busy(", "function arrive(",
           "function setText(", "function setMsg(", "function scramble(", "function pop(", "function relayout(",
           "function removeEl(", "function addEl(", "function buildSeg(", "function markSeg("]


def test_index_uses_shared_files():
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="shared.css">' in html
    assert '<script src="shared.js"></script>' in html
    assert "--panel:" not in html  # tokens live only in shared.css
    assert not any(h in html for h in HELPERS)  # helpers live only in shared.js


def test_shared_files_define_everything():
    css = (UI / "shared.css").read_text(encoding="utf-8")
    js = (UI / "shared.js").read_text(encoding="utf-8")
    assert "--panel: #16202B" in css and "--uni: #9085e9" in css and ".btn.primary" in css
    assert all(h in js for h in HELPERS)
def test_widget_uses_shared_files():
    html = (UI / "widget.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="shared.css">' in html and '<script src="shared.js"></script>' in html
    assert "--panel:" not in html and not any(h in html for h in HELPERS)
