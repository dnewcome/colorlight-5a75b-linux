#!/bin/bash
# Launch LEDVISION 8.8 under Wine with raw-socket rights, inside a private network
# namespace that contains ONLY a macvlan child of eno1.  LEDVISION crashes when it
# sees this PC's ~23 interfaces (docker bridges/veths), so we hide them.
# Run as:  sudo ./run-ledvision.sh
set -e
TRACE=""; if [ "$1" = "--trace" ]; then TRACE="+relay,+seh,+loaddll"; shift; fi
if [ "$(id -u)" != 0 ]; then echo "run with sudo"; exit 1; fi
PARENT=${PARENT:-eno1}; NS=clnet; IF=cl0
SRC=/home/dan/.wine-ledvision; DST=/root/.wine-ledvision
LOG=/home/dan/sandbox/dnuke-art/hub75-board/ledvision/run-root.log

echo "syncing prefix $SRC -> $DST ..."; rsync -a --delete --exclude="drive_c/users/root" "$SRC/" "$DST/"; chown -R root:root "$DST"
mkdir -p /root/Documents /root/Desktop "$DST/drive_c/users/root/Documents" "$DST/drive_c/users/root/Desktop" "$DST/drive_c/users/root/AppData/Local" "$DST/drive_c/users/root/AppData/Roaming"

# --- network namespace with a single macvlan interface on top of $PARENT ---
ip netns list | grep -qw "$NS" || ip netns add "$NS"
if ! ip -n "$NS" link show "$IF" >/dev/null 2>&1; then
  ip link show "$IF" >/dev/null 2>&1 && ip link del "$IF"
  ip link add "$IF" link "$PARENT" type macvlan mode bridge
  ip link set "$IF" netns "$NS"
fi
ip -n "$NS" link set lo up
ip -n "$NS" link set "$IF" up
ip -n "$NS" link set "$IF" promisc on
ip -n "$NS" addr show "$IF" | grep -q "inet " || ip -n "$NS" addr add 169.254.75.1/16 dev "$IF"
ip link set "$PARENT" promisc on
echo "namespace $NS:"; ip -n "$NS" -br addr

export HOME=/root WINEPREFIX="$DST" WINEDEBUG="${TRACE:-+seh,+loaddll}"
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-/run/user/1000/.mutter-Xwaylandauth.U8TJV3}"
SHIMLOG=/home/dan/sandbox/dnuke-art/hub75-board/ledvision/wpcap-shim.log; touch "$SHIMLOG"; chown dan:dan "$SHIMLOG"; ln -sfn "$SHIMLOG" "$DST/drive_c/wpcap-shim.log"
echo "logging wine output to $LOG, shim log to $SHIMLOG"
cd "$DST/drive_c/Program Files (x86)/ColorLight/LEDVISION"
exec ip netns exec "$NS" wine explorer /desktop=LEDVISION,${DESKSIZE:-2560x1440} \
     "C:\\Program Files (x86)\\ColorLight\\LEDVISION\\LEDVISION.exe" "$@" > "$LOG" 2>&1
