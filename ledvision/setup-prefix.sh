#!/bin/bash
# One-time setup of the LEDVISION Wine prefix.  Run as your normal user (no sudo).
set -e
cd "$(dirname "$0")"
export WINEPREFIX=$HOME/.wine-ledvision WINEDEBUG=-all
[ -f LEDVISION_Setup_8.8.41357.exe ] || unzip -o ledvision-8.8.zip
wineboot -i
# LEDVISION installer (NSIS).  Its bundled WinPcap sub-installer hangs under Wine: kill it.
( sleep 90; pkill -f WinPcap_4_1_3.exe || true ) &
wine LEDVISION_Setup_8.8.41357.exe /S || true
APP="$WINEPREFIX/drive_c/Program Files (x86)/ColorLight/LEDVISION"
[ -f "$APP/LEDVISION.exe" ] || { echo "install failed"; exit 1; }
# WinPcap presence check
wine reg add "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\WinPcapInst" /reg:32 /v DisplayName /t REG_SZ /d "WinPcap 4.1.3" /f
wine reg add "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\WinPcapInst" /reg:32 /v DisplayVersion /t REG_SZ /d "4.1.0.2980" /f
# Genuine VC2013 runtime + MFC (LEDVISION bundles native mfc120u; Wine's fake msvcr120 has a higher
# version number so the redistributable's MSI won't replace it -- extract the files by hand).
winetricks -q vcrun2013 || true
T=$(mktemp -d); ( cd "$T" && cabextract -q -d . "$HOME/.cache/winetricks/vcrun2013/vcredist_x86.exe" && cabextract -q -d ex a2 a2 && cabextract -q -d ex a3 a3 )
cp "$T/ex/F_CENTRAL_msvcr120_x86" "$WINEPREFIX/drive_c/windows/syswow64/msvcr120.dll"
cp "$T/ex/F_CENTRAL_msvcp120_x86" "$WINEPREFIX/drive_c/windows/syswow64/msvcp120.dll"
cp "$T/ex/F_CENTRAL_mfc120u_x86"  "$WINEPREFIX/drive_c/windows/syswow64/mfc120u.dll"
rm -rf "$T"
wine reg add "HKCU\\Software\\Wine\\DllOverrides" /v msvcr120 /t REG_SZ /d native /f
wine reg add "HKCU\\Software\\Wine\\DllOverrides" /v msvcp120 /t REG_SZ /d native /f
# WinPcap send-queue shim
[ -f shim/wpcap.dll ] || shim/build.sh
cp shim/wpcap.dll "$APP/wpcap.dll"
wine reg add "HKCU\\Software\\Wine\\DllOverrides" /v wpcap /t REG_SZ /d "native,builtin" /f
wineserver -w
echo "prefix ready: $WINEPREFIX"
