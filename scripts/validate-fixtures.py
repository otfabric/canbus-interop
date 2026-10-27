#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate the fixtures: frame documents against schemas/frame.schema.json and
the cross-field rules of the contract (CAN FD lengths, remote frames, ranges);
DBC vectors against the DBC they belong to; encode inputs against
schemas/encode-input.schema.json.

--require-schema fails when the jsonschema package is missing instead of
checking the cross-field rules only.
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FD_LENGTHS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64}


def lines(path):
    with open(path) as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if line and not line.startswith("#"):
                yield n, json.loads(line)


def frame_rules(d):
    data = bytes.fromhex(d.get("data", ""))
    ext, fd, remote = d.get("extended", False), d.get("fd", False), d.get("remote", False)
    if d["id"] > (0x1FFFFFFF if ext or d.get("error") else 0x7FF):
        return "identifier out of range"
    if fd and remote:
        return "CAN FD remote frame"
    if fd and d["len"] not in FD_LENGTHS:
        return "invalid CAN FD length"
    if not fd and (d["len"] > 8 or d.get("brs") or d.get("esi")):
        return "classical frame with len > 8 or BRS/ESI"
    if remote and data:
        return "remote frame with data"
    if not remote and len(data) != d["len"]:
        return "len does not match data"
    return None


def main():
    require = "--require-schema" in sys.argv
    try:
        import jsonschema
    except ImportError:
        if require:
            sys.exit("jsonschema is not installed")
        jsonschema = None
    schema = lambda n: json.load(open(os.path.join(ROOT, "schemas", n)))
    errors, count = [], 0
    fv = jsonschema.Draft202012Validator(schema("frame.schema.json")) if jsonschema else None
    ev = jsonschema.Draft202012Validator(schema("encode-input.schema.json")) if jsonschema else None
    frame_files = glob.glob(os.path.join(ROOT, "fixtures", "frames", "*.jsonl")) + \
        glob.glob(os.path.join(ROOT, "fixtures", "dbc", "*.frames.jsonl")) + \
        glob.glob(os.path.join(ROOT, "fixtures", "kcd", "*.frames.jsonl")) + \
        glob.glob(os.path.join(ROOT, "fixtures", "arxml", "*.frames.jsonl")) + \
        [os.path.join(ROOT, "fixtures", "logs", "frames.jsonl")]
    for path in sorted(frame_files):
        for n, d in lines(path):
            count += 1
            if fv:
                errors += ["%s:%d: %s" % (path, n, e.message) for e in fv.iter_errors(d)]
            rule = frame_rules(d)
            if rule:
                errors.append("%s:%d: %s" % (path, n, rule))
    for path in sorted(glob.glob(os.path.join(ROOT, "fixtures", "dbc", "*.messages.jsonl"))):
        dbc = open(path.replace(".messages.jsonl", ".dbc")).read()
        messages = {}
        for m in re.finditer(r"^BO_ \d+ (\w+):[^\n]*\n((?: SG_[^\n]*\n)*)", dbc, re.M):
            messages[m.group(1)] = set(re.findall(r"^ SG_ (\w+)", m.group(2), re.M))
        for n, d in lines(path):
            count += 1
            if ev:
                errors += ["%s:%d: %s" % (path, n, e.message) for e in ev.iter_errors(d)]
            if d["message"] not in messages:
                errors.append("%s:%d: no message %s in the DBC" % (path, n, d["message"]))
            else:
                for s in d["signals"]:
                    if s not in messages[d["message"]]:
                        errors.append("%s:%d: no signal %s in %s" % (path, n, s, d["message"]))
    # ARXML: messages are CAN-FRAME short names, signals I-SIGNAL short names
    # mapped into the frame's PDU (the fixtures map one PDU per frame).
    for path in sorted(glob.glob(os.path.join(ROOT, "fixtures", "arxml", "*.messages.jsonl"))):
        xml = open(path.replace(".messages.jsonl", ".arxml")).read()
        pdu_signals = {}
        for m in re.finditer(r"<I-SIGNAL-I-PDU>\s*<SHORT-NAME>(\w+)</SHORT-NAME>(.*?)</I-SIGNAL-I-PDU>", xml, re.S):
            pdu_signals[m.group(1)] = set(re.findall(r"/Signals/(\w+)</I-SIGNAL-REF>", m.group(2)))
        messages = {}
        for m in re.finditer(r"<CAN-FRAME>\s*<SHORT-NAME>(\w+)</SHORT-NAME>(.*?)</CAN-FRAME>", xml, re.S):
            pdus = re.findall(r"/Pdus/(\w+)</PDU-REF>", m.group(2))
            messages[m.group(1)] = set().union(*(pdu_signals.get(p, set()) for p in pdus))
        for n, d in lines(path):
            count += 1
            if ev:
                errors += ["%s:%d: %s" % (path, n, e.message) for e in ev.iter_errors(d)]
            if d["message"] not in messages:
                errors.append("%s:%d: no frame %s in the ARXML" % (path, n, d["message"]))
            else:
                for sig in d["signals"]:
                    if sig not in messages[d["message"]]:
                        errors.append("%s:%d: no signal %s in %s" % (path, n, sig, d["message"]))
    for arxml in sorted(glob.glob(os.path.join(ROOT, "fixtures", "arxml", "*.arxml"))):
        if not os.path.exists(arxml[:-6] + ".frames.jsonl"):
            errors.append("%s: no .frames.jsonl vectors" % arxml)
    for dbc in sorted(glob.glob(os.path.join(ROOT, "fixtures", "dbc", "*.dbc"))):
        base = dbc[:-4]
        if not os.path.exists(base + ".frames.jsonl"):
            errors.append("%s: no .frames.jsonl vectors" % dbc)
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print("%d fixture documents valid%s" % (count, "" if jsonschema else " (cross-field rules only)"))


if __name__ == "__main__":
    main()
