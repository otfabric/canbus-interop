#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# interop.sh <adapter> [<adapter> ...]: the cross-stack self-test of these
# adapters against each other on vcan (scripts/selftest.py): every pair that
# both sides' capabilities allow, an adapter with itself included. Make the
# vcan interfaces first (make vcan).
#
# This tests the adapters against each other. It says nothing about any
# library that consumes the images.
#
# Environment: as scripts/lib.sh (REGISTRY, VERSION, IMAGE_TEMPLATE,
#              ADAPTER_IMAGE_<adapter>) and scripts/selftest.py (SUITES, VCAN,
#              VCAN2, VCANXL, ADMIN, DOCKER); REPORT_DIR (default reports).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/lib.sh"

[[ $# -ge 1 ]] || { echo "usage: interop.sh <adapter> [<adapter> ...]" >&2; exit 2; }
for a in "$@"; do
    echo "[interop] ${a}: $(image_of "${a}")" >&2
done
ADAPTERS="$*" exec python3 "${SCRIPT_DIR}/selftest.py" --reports "${REPORT_DIR:-${REPORTS:-reports}}"
