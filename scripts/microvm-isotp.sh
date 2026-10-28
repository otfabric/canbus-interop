#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# microvm-isotp.sh: run the self-test's isotp suite in a virtme-ng microVM
# booted with the stock Ubuntu generic kernel (which ships can-isotp), on a
# host with KVM. The adapter images are exported to root file systems on the
# host (scripts/chroot-run export) and run inside the guest with chroot: no
# Docker daemon in the guest. Needs: Docker, qemu-system-x86, virtme-ng
# (vng), the built images ghcr.io/otfabric/canbus-interop-{canutils,
# pythoncanisotp,pythoncan}:$VERSION.
#
#   scripts/microvm-isotp.sh [reports-dir]
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
reports=$(realpath -m "${1:-$root/reports-microvm}")
version=${VERSION:-dev}
state=$(mktemp -d /var/tmp/cbi-microvm.XXXXXX)
export ROOTFS=$state/rootfs
mkdir -p "$state/work" "$reports" "$ROOTFS/run"
chmod 777 "$state/work" "$reports"

# The kernel: Ubuntu's generic build of this release, unpacked, not installed.
ver=$(apt-cache depends linux-image-generic | sed -n 's/.*linux-image-\([0-9].*-generic\)$/\1/p' | head -1)
(cd "$state" && apt-get download -q "linux-image-unsigned-$ver" "linux-modules-$ver" "linux-modules-extra-$ver" >/dev/null \
    && for d in *.deb; do dpkg-deb -x "$d" kernel; done)
sudo depmod -b "$state/kernel" "$ver"

"$root/scripts/chroot-run" export \
    "ghcr.io/otfabric/canbus-interop-canutils:$version" \
    "ghcr.io/otfabric/canbus-interop-pythoncanisotp:$version" \
    "ghcr.io/otfabric/canbus-interop-pythoncan:$version"

cat > "$state/guest.sh" <<GUEST
set -e
uname -r
export MODPROBE_OPTIONS="-d $state/kernel"
modprobe -a can can-raw vcan can-isotp
for i in 0 1; do ip link add vcan\$i type vcan; ip link set vcan\$i mtu 72 up; done
cd "$root"
env ROOTFS="$ROOTFS" DOCKER="$root/scripts/chroot-run" ADMIN="" \
    IMAGE_TEMPLATE="ghcr.io/otfabric/canbus-interop-{adapter}:$version" \
    ADAPTERS="canutils pythoncanisotp pythoncan" SUITES=isotp \
    WORK="$state/work" python3 scripts/selftest.py --reports "$reports"
GUEST
start=$(date +%s)
vng --run "$state/kernel/boot/vmlinuz-$ver" --root / --user root --memory 2G --cpus 2 \
    --rwdir "$state" --rwdir "$reports" --exec "bash $state/guest.sh"
echo "microVM with Linux $ver: $(( $(date +%s) - start )) s"
