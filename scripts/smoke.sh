#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# smoke.sh [adapter...]: the contract checks that need no CAN interface. For
# every image: print-capabilities and print-version documents, print-fixture,
# exit 2 with an error document for an unsupported operation and for a usage
# error. Documents go to $REPORTS/smoke (validate with validate-documents.py).
#
# Environment: DOCKER (default docker), as scripts/lib.sh (REGISTRY, VERSION,
#              IMAGE_TEMPLATE, ADAPTER_IMAGE_<adapter>), REPORT_DIR or REPORTS
#              (default reports).
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh
read -r -a DOCKER <<< "${DOCKER:-docker}"
OUT="${REPORT_DIR:-${REPORTS:-reports}}/smoke"
mkdir -p "$OUT"
[[ $# -gt 0 ]] || set -- canutils pythoncan socketcanrs scapy pythoncanisotp cantools canmatrix
fail=0
for a in "$@"; do
    img=$(image_of "$a")
    run() { "${DOCKER[@]}" run --rm -i "$img" "$@"; }
    run print-capabilities > "$OUT/$a.capabilities.json"
    run print-version > "$OUT/$a.version.json"
    if ! run print-fixture frames/standard.jsonl | cmp -s - fixtures/frames/standard.jsonl; then
        echo "FAIL $a: print-fixture differs from fixtures/frames/standard.jsonl"; fail=1
    fi
    ops=$(python3 -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["operations"]))' "$OUT/$a.capabilities.json")
    unsupported=""
    for op in send receive capture replay decode encode isotp-send isotp-receive convert; do
        [[ " $ops " == *" $op "* ]] || { unsupported=$op; break; }
    done
    if [[ -n "$unsupported" ]]; then
        set +e; run "$unsupported" > "$OUT/$a.unsupported.jsonl" 2>/dev/null; code=$?; set -e
        if [[ $code -ne 2 ]] || ! grep -q '"code":"unsupported"' "$OUT/$a.unsupported.jsonl"; then
            echo "FAIL $a: $unsupported should exit 2 with code unsupported (exit $code)"; fail=1
        fi
    fi
    set +e; run "${ops%% *}" --no-such-flag > "$OUT/$a.usage.jsonl" 2>/dev/null; code=$?; set -e
    if [[ $code -ne 2 ]] || ! grep -q '"type":"error"' "$OUT/$a.usage.jsonl"; then
        echo "FAIL $a: an unknown flag should exit 2 with an error document (exit $code)"; fail=1
    fi
    # (1.4) The image says whether it is an independent implementation.
    if ! python3 -c 'import json,sys; sys.exit(not isinstance(json.load(open(sys.argv[1])).get("independentEngine"), bool))' "$OUT/$a.version.json"; then
        echo "FAIL $a: print-version has no boolean independentEngine"; fail=1
    fi
    echo "ok   $a: $(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["upstream"], d["version"])' "$OUT/$a.version.json") [$ops]"
done
exit $fail
