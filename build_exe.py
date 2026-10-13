"""Build dist/UnigenManager.exe: one file, no console, runs without Python installed.

    py -3.10 -m pip install -r requirements-dev.txt
    py -3.10 build_exe.py
"""
import subprocess, sys
from pathlib import Path

import tray

ROOT = Path(__file__).resolve().parent
BUILD, DIST = ROOT / "build", ROOT / "dist"


def make_icon(path):
    """The tray's cyan signal arcs on the app's dark panel, at every size Windows asks for."""
    from PIL import Image
    big = Image.new("RGBA", (256, 256), (22, 32, 43, 255))  # --panel
    big.alpha_composite(tray.icon_image(256))
    big.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main():
    BUILD.mkdir(exist_ok=True)
    icon = BUILD / "unigen.ico"
    make_icon(icon)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--name", "UnigenManager", "--icon", str(icon),
        "--add-data", f"{ROOT / 'ui'};ui",          # the pages, shared.js/css, mock and vendored anime.js
        "--add-data", f"{ROOT / 'bt.ps1'};.",       # bt.py reads it next to itself
        "--hidden-import", "pystray._win32",       # pystray picks its backend at runtime
        "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"), "--specpath", str(BUILD),
        str(ROOT / "UnigenManager.pyw"),
    ], check=True)
    exe = DIST / "UnigenManager.exe"
    print(f"\nBuilt {exe} ({exe.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
