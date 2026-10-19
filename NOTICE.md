# Notices

Unigen Manager is MIT-licensed ([LICENSE](LICENSE)). The two items below are not part of that licence.

## The dongle's Wi-Fi driver (downloaded on demand, not shipped)

The driver the app installs on request (**Download & install**, `driver.py`) is the Windows driver of the **AIC8800D80** Wi-Fi chip, made and signed by **AIC Semiconductor (Shanghai) Co., Ltd.** (the catalogs carry a Microsoft Windows Hardware Compatibility signature). It is not distributed with this app. The app downloads AIC's own installer from a community mirror and unpacks the driver files from it, without running the installer:

- Mirror: <https://github.com/peckishrine/aic8800_windows_drivers>, pinned to commit `d95fedce4c3ecf0a9d43fc5a899631880231c460`
- File: `drivers/Latest_Driver_AX900_USB_WiFi_6_and_Bluetooth_Adapter.exe` (3,322,984 bytes)
- SHA-256: `151e305aa1231085ad225638b03fd53c6c1b05f69f5a042db4f826ae794970a4`

The mirror repository states no licence, so no right to redistribute AIC's files is assumed; that is why they are fetched from there at the user's request instead of being bundled. The driver stays under AIC's own terms.

## innoextract (bundled in `tools/innoextract/`)

`innoextract.exe` is [innoextract](https://constexpr.org/innoextract/) **1.9**, the unmodified Windows build from the project's website (`innoextract-1.9-windows.zip`, SHA-256 of the zip `6989342c9b026a00a72a38f23b62a8e6a22cc5de69805cf47d68ac2fec993065`), Copyright (C) 2011-2020 Daniel Scharrer. It is used only to unpack the driver files from the installer above. It is released under the **zlib licence** (`tools/innoextract/license/innoextract.LICENSE.txt`); the binary also contains parts of these, whose licences are included in the same folder:

- libstdc++ (GPLv3 with the GCC Runtime Library Exception): `libstdc++.COPYING3.txt`, `libstdc++.COPYING.RUNTIME.txt`
- liblzma (public domain): `liblzma.COPYING.txt`
- Boost (Boost Software Licence 1.0): `Boost.LICENSE_1_0.txt`

Source code: <https://constexpr.org/innoextract/> (the release archives and the git repository linked there).
