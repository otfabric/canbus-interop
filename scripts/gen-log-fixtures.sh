#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# gen-log-fixtures.sh [image]: regenerate fixtures/logs/ with python-can's
# own writers (the pythoncan image's log-convert): frames.jsonl (the source:
# fixtures/frames/mixed, fd and remote with timestamps 1 ms apart) written as
# Vector ASC, Vector BLF and PEAK TRC, and <format>.read.jsonl, what
# python-can reads back from each file (the reference reading, with that
# format's losses; see docs/LOG_FORMATS.md). ASC files carry the date of
# writing in their header, so a regenerated ASC file differs in that line.
set -euo pipefail
image=${1:-ghcr.io/otfabric/canbus-interop-pythoncan:dev}
dir=$(cd "$(dirname "$0")/.." && pwd)/fixtures/logs
work=$(mktemp -d)
chmod 777 "$work"
python3 - "$dir/../frames" "$work/frames.jsonl" <<'PY'
import json, sys
src, out = sys.argv[1], sys.argv[2]
t = 1700000000.0
with open(out, "w") as o:
    o.write("# Source of the log fixtures: fixtures/frames/mixed, fd and remote, 1 ms apart\n")
    i = 0
    for name in ("mixed", "fd", "remote"):
        for line in open("%s/%s.jsonl" % (src, name)):
            line = line.strip()
            if not line or line[0] == "#":
                continue
            d = json.loads(line)
            d["timestamp"] = "%.6f" % (t + i * 0.001)
            o.write(json.dumps(d) + "\n")
            i += 1
PY
for ext in asc blf trc; do
    docker run --rm -v "$work:/work" "$image" log-convert --input /work/frames.jsonl --output "/work/frames.$ext" >/dev/null
    docker run --rm -v "$work:/work" "$image" log-convert --input "/work/frames.$ext" --output "/work/$ext.read.jsonl" >/dev/null
done
cp "$work"/frames.jsonl "$work"/frames.asc "$work"/frames.blf "$work"/frames.trc "$work"/*.read.jsonl "$dir/"
rm -rf "$work"
ls -l "$dir"
