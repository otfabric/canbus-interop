#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# setup-vcan.sh [interface...]: load the CAN modules and create CAN FD capable
# vcan interfaces (default vcan0 vcan1) in the current network namespace.
# Needs root (run with sudo). Idempotent.
set -euo pipefail

modprobe -a can can-raw vcan 2>/dev/null || {
    echo "setup-vcan: cannot load the CAN modules; on Ubuntu install linux-modules-extra-\$(uname -r)" >&2
    exit 4
}
[[ -d /sys/module/can_isotp ]] || modprobe can-isotp 2>/dev/null ||
    echo "setup-vcan: no can-isotp module: the kernel ISO-TP scenarios will be skipped" >&2
[[ $# -gt 0 ]] || set -- vcan0 vcan1
for ifc in "$@"; do
    ip link show "$ifc" >/dev/null 2>&1 || ip link add dev "$ifc" type vcan
    ip link set "$ifc" down
    ip link set "$ifc" mtu 72          # CAN FD frames (CANFD_MTU)
    ip link set "$ifc" txqueuelen 1000 # bursts without ENOBUFS
    ip link set "$ifc" up
done
ip -br link show type vcan
