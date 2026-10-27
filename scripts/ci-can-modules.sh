#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# ci-can-modules.sh: make the CAN modules (can, can-raw, vcan, can-isotp)
# loadable on a GitHub-hosted Ubuntu runner. They are in the kernel's
# linux-modules-extra package, which is not installed; when the archive has
# no package for the running kernel yet, the one of the same kernel from the
# release pocket is looked up by its ABI.
set -euo pipefail

mods=(can can-raw vcan can-isotp)
if sudo modprobe -a "${mods[@]}" 2>/dev/null; then
    echo "CAN modules already available for $(uname -r)"
    exit 0
fi
kernel=$(uname -r)
echo "Installing linux-modules-extra-${kernel}"
sudo apt-get update -q
if ! sudo apt-get install -y -q "linux-modules-extra-${kernel}"; then
    echo "::warning::no linux-modules-extra-${kernel}; candidates:"
    apt-cache search --names-only "^linux-modules-extra-${kernel%%-*}" | head -20 || true
    find "/lib/modules/${kernel}" -name 'vcan*' -o -name 'can-isotp*' || true
    exit 1
fi
sudo modprobe -a "${mods[@]}"
echo "CAN modules loaded for ${kernel}"
