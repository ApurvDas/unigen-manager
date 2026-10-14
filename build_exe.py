"""Build dist/UnigenManager.exe: one file, no console, runs without Python installed.

    py -3.10 -m pip install -r requirements-dev.txt
    py -3.10 build_exe.py
"""
import subprocess, sys
from pathlib import Path

import tray
from version import VERSION

ROOT = Path(__file__).resolve().parent
BUILD, DIST = ROOT / "build", ROOT / "dist"


def make_icon(path):
    """The tray's cyan signal arcs on the app's dark panel, at every size Windows asks for."""
    from PIL import Image
    big = Image.new("RGBA", (256, 256), (22, 32, 43, 255))  # --panel
    big.alpha_composite(tray.icon_image(256))
    big.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def version_file(path):
    """Windows file properties (Details tab): product name and version."""
    nums = tuple(map(int, VERSION.split("."))) + (0,)
    strings = {"CompanyName": "Unigen Manager", "FileDescription": "Unigen Manager", "ProductName": "Unigen Manager",
               "FileVersion": VERSION, "ProductVersion": VERSION, "OriginalFilename": "UnigenManager.exe",
               "LegalCopyright": "Unofficial, not affiliated with Unigen"}
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}),
  kids=[StringFileInfo([StringTable('040904B0', [{", ".join(f"StringStruct({k!r}, {v!r})" for k, v in strings.items())}])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")


def main():
    BUILD.mkdir(exist_ok=True)
    icon = BUILD / "unigen.ico"
    make_icon(icon)
    info = BUILD / "version.txt"
    version_file(info)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--name", "UnigenManager", "--icon", str(icon), "--version-file", str(info),
        "--add-data", f"{ROOT / 'ui'};ui",          # the pages, shared.js/css, mock and vendored anime.js
        "--hidden-import", "pystray._win32",       # pystray picks its backend at runtime
        "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"), "--specpath", str(BUILD),
        str(ROOT / "UnigenManager.pyw"),
    ], check=True)
    exe = DIST / "UnigenManager.exe"
    print(f"\nBuilt {exe} ({exe.stat().st_size / 1e6:.1f} MB), version {VERSION}: release it as v{VERSION}")


if __name__ == "__main__":
    main()
