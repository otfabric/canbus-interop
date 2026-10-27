#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reference-to-reference self-test of the canbus-interop images.

Runs every applicable pair of adapters against each other on Linux vcan
interfaces and checks the documents of docs/CONTAINER_CONTRACT.md:

  raw     frame fixtures, burst, filters, loopback, receive-own, several
          receivers, capture/replay, malformed input, interface down/missing
  isotp   kernel CAN_ISOTP (canutils) <-> python-can-isotp, both directions;
          invalid sequences injected with a raw-CAN adapter
  dbc     cantools <-> canmatrix decode and encode agreement on the DBC
          fixtures (tests/known-differences.tsv lists accepted differences)

Selection is capability driven: a pair or scenario an adapter cannot do is
recorded as "skip" with the reason, never as "pass". Results go to
<reports>/selftest.json and <reports>/selftest.md; the exit status is 1 when a
scenario failed.

Environment:
  DOCKER            docker command (default "docker"; e.g. "sudo docker")
  IMAGE_TEMPLATE    image name with {adapter} (default
                    "ghcr.io/otfabric/canbus-interop-{adapter}:dev")
  ADAPTERS          space-separated subset (default: all)
  SUITES            space-separated subset of raw isotp dbc (default: all)
  VCAN, VCAN2       interfaces (default vcan0, vcan1)
  ADMIN             prefix for "ip link" (default "sudo"; "" when root);
                    set ADMIN=none to skip the interface down/up scenarios
  REPORTS           report directory (default ./reports)
  WORK              scratch directory shared with the containers (default
                    a new directory under /tmp)
"""

import argparse
import json
import os
import queue
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALL_ADAPTERS = ["canutils", "pythoncan", "socketcanrs", "scapy", "pythoncanisotp", "cantools", "canmatrix"]

DOCKER = shlex.split(os.environ.get("DOCKER", "docker"))
TEMPLATE = os.environ.get("IMAGE_TEMPLATE", "ghcr.io/otfabric/canbus-interop-{adapter}:dev")
VCAN = os.environ.get("VCAN", "vcan0")
VCAN2 = os.environ.get("VCAN2", "vcan1")
ADMIN = os.environ.get("ADMIN", "sudo")
WORK = os.environ.get("WORK") or tempfile.mkdtemp(prefix="canbus-selftest-")
os.chmod(WORK, 0o777)

FRAME_KEYS = ("id", "extended", "fd", "brs", "esi", "remote", "error", "len", "data")
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_SFF_MASK = 0x7FF

results = []
DOCS = {}   # adapter -> every JSON document its containers printed


def keep(adapter, docs):
    DOCS.setdefault(adapter, []).extend(docs)


def image(adapter):
    return TEMPLATE.format(adapter=adapter)


def record(suite, scenario, status, detail="", sender="", receiver="", duration=0.0):
    r = {"suite": suite, "scenario": scenario, "sender": sender, "receiver": receiver,
         "status": status, "detail": detail, "seconds": round(duration, 2)}
    results.append(r)
    pair = (sender + " -> " + receiver) if sender or receiver else ""
    print("%-5s %-6s %-28s %-30s %s" % (status.upper(), suite, scenario, pair, detail), flush=True)


# ── containers ──────────────────────────────────────────────────────────────

def docker_argv(adapter, args, name=None):
    argv = DOCKER + ["run", "--rm", "-i", "--network", "host", "-v", "%s:/work" % WORK]
    if name:
        argv += ["--name", name]
    return argv + [image(adapter)] + args


def parse_docs(text):
    docs = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                docs.append(json.loads(line))
            except ValueError:
                pass
    return docs


def run(adapter, args, stdin=None, timeout=60):
    """Run a container to completion: (exit code, documents, stderr)."""
    try:
        p = subprocess.run(docker_argv(adapter, args), input=stdin, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, [], "harness timeout"
    docs = parse_docs(p.stdout)
    if args and args[0] not in ("print-capabilities", "print-version"):
        keep(adapter, docs)
    return p.returncode, docs, p.stderr


class Background:
    """A container whose stdout is read line by line (receivers)."""

    def __init__(self, adapter, args):
        self.adapter = adapter
        self.name = "cbi-" + uuid.uuid4().hex[:10]
        self.proc = subprocess.Popen(docker_argv(adapter, args, self.name), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.lines = queue.Queue()
        self.docs = []
        self.stderr = ""
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _read_err(self):
        self.stderr = self.proc.stderr.read()

    def wait_ready(self, timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                line = self.lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                return False
            docs = parse_docs(line)
            self.docs += docs
            if any(d.get("type") == "ready" for d in docs):
                return True
        return False

    def finish(self, timeout=60):
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(DOCKER + ["kill", self.name], capture_output=True)
            self.proc.wait()
        while True:
            try:
                line = self.lines.get(timeout=2)
            except queue.Empty:
                break
            if line is None:
                break
            self.docs += parse_docs(line)
        keep(self.adapter, self.docs)
        return self.proc.returncode

    def frames(self):
        return [d["frame"] for d in self.docs if d.get("type") == "frame"]

    def messages(self):
        return [d for d in self.docs if d.get("type") == "message"]

    def error(self):
        errs = [d for d in self.docs if d.get("type") == "error"]
        return errs[-1].get("message", "") if errs else self.stderr.strip()[-300:]


def capabilities(adapter):
    code, docs, err = run(adapter, ["print-capabilities"], timeout=120)
    if code != 0 or not docs:
        raise SystemExit("cannot read the capabilities of %s (%s): %s" % (adapter, image(adapter), err))
    return docs[0]


# ── fixtures ────────────────────────────────────────────────────────────────

def load_jsonl(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(json.loads(line))
    return out


def frames_fixture(name):
    return load_jsonl(os.path.join(ROOT, "fixtures", "frames", name + ".jsonl"))


def norm(frame):
    return {k: frame.get(k) for k in FRAME_KEYS}


def compare_frames(expected, got):
    """None when equal (in order), else a short description of the first difference."""
    exp = [norm(f) for f in expected]
    act = [norm(f) for f in got]
    if len(act) != len(exp):
        missing = len(exp) - len(act)
        detail = "received %d of %d frames" % (len(act), len(exp))
        if missing > 0 and act:
            seen = {json.dumps(a, sort_keys=True) for a in act}
            first = next((e for e in exp if json.dumps(e, sort_keys=True) not in seen), None)
            if first:
                detail += "; first missing %s" % json.dumps(first, sort_keys=True)
        return detail
    for i, (e, a) in enumerate(zip(exp, act)):
        if e != a:
            return "frame %d: expected %s got %s" % (i, json.dumps(e, sort_keys=True), json.dumps(a, sort_keys=True))
    return None


def write_work(name, docs):
    path = os.path.join(WORK, name)
    with open(path, "w") as f:
        for d in docs:
            f.write(json.dumps(d) + "\n")
    os.chmod(path, 0o666)
    return "/work/" + name


# ── raw CAN ─────────────────────────────────────────────────────────────────

RAW_FIXTURES = {
    # fixture: (features the sender needs, features the receiver needs, --fd)
    "standard": ([], [], False),
    "extended": ([], [], False),
    "remote": (["remote"], ["remote"], False),
    "fd": (["fd", "brs"], ["fd"], True),
    "fd-esi": (["fd", "esi"], ["fd"], True),
    "burst": ([], [], False),
}

# Error frames: injected from userspace (only vcan lets a socket send them),
# received with --error-mask; a receiver without it must not see them.
ERROR_MASK = "1FFFFFFF"

# Pause between frames of the paced burst: about the frame rate of a 500
# kbit/s bus. Unpaced, a userspace receiver falls behind and the kernel drops
# frames from its full socket buffer (see burst-unpaced).
BURST_GAP_US = "250"


def missing(caps, features):
    return [f for f in features if not caps["features"].get(f)]


def transfer(sender, receiver, frames, fd, send_extra=(), recv_extra=(), interface=VCAN,
             count=None, timeout_ms=20000, frames_file=None):
    """Start the receiver, send, collect. Returns (receiver, send exit, send docs)."""
    count = len(frames) if count is None else count
    rargs = ["receive", "--interface", interface, "--count", str(count), "--timeout-ms", str(timeout_ms)]
    rargs += (["--fd"] if fd else []) + list(recv_extra)
    rx = Background(receiver, rargs)
    if not rx.wait_ready():
        rx.finish(5)
        return rx, None, []
    path = frames_file or write_work("frames-%s.jsonl" % uuid.uuid4().hex[:8], frames)
    sargs = ["send", "--interface", interface, "--frames", path] + (["--fd"] if fd else []) + list(send_extra)
    code, docs, _ = run(sender, sargs, timeout=timeout_ms / 1000 + 60)
    rx.finish(timeout_ms / 1000 + 30)
    return rx, code, docs


def suite_raw(caps):
    senders = [a for a in caps if "send" in caps[a]["operations"]]
    receivers = [a for a in caps if "receive" in caps[a]["operations"]]

    # Every fixture, every pair (an adapter with itself included).
    for fixture, (sneed, rneed, fd) in RAW_FIXTURES.items():
        frames = frames_fixture(fixture)
        for s in senders:
            for r in receivers:
                why = missing(caps[s], sneed) + ["receiver:" + m for m in missing(caps[r], rneed)]
                if why:
                    record("raw", "frames-" + fixture, "skip", "lacks " + ",".join(why), s, r)
                    continue
                t0 = time.monotonic()
                rx, scode, _ = transfer(s, r, frames, fd, frames_file="/fixtures/frames/%s.jsonl" % fixture,
                                        send_extra=["--gap-us", BURST_GAP_US] if fixture == "burst" else [],
                                        timeout_ms=60000 if fixture == "burst" else 20000)
                dur = time.monotonic() - t0
                if scode is None:
                    record("raw", "frames-" + fixture, "fail", "receiver not ready: " + rx.error(), s, r, dur)
                elif scode != 0:
                    record("raw", "frames-" + fixture, "fail", "sender exit %d" % scode, s, r, dur)
                else:
                    diff = compare_frames(frames, rx.frames())
                    if diff:
                        record("raw", "frames-" + fixture, "fail", diff, s, r, dur)
                    else:
                        record("raw", "frames-" + fixture, "pass", "%d frames" % len(frames), s, r, dur)

    for s in senders:
        for r in receivers:
            suite_burst_unpaced(s, r)
            suite_error_frames(caps, s, r)

    sender = next((a for a in ("pythoncan", "socketcanrs", "canutils", "scapy") if a in senders), None)
    if sender:
        suite_filters(caps, sender, receivers)
        suite_multi(caps, sender, receivers)
    for s in senders:
        suite_loopback(caps, s, receivers)
        suite_recv_own(caps, s)
        suite_malformed(caps, s)
    suite_capture_replay(caps, sender, receivers)
    suite_interfaces(caps, sender, receivers)


def suite_burst_unpaced(s, r):
    """As fast as the sender can: order must hold; losses are counted.

    Receivers are userspace programs writing JSON through a pipe; the kernel
    drops what does not fit their socket buffer. Pass = the frames that
    arrived are in sending order without duplicates; the loss is reported.
    """
    frames = frames_fixture("burst")
    t0 = time.monotonic()
    rx, scode, _ = transfer(s, r, frames, False, frames_file="/fixtures/frames/burst.jsonl", timeout_ms=8000)
    dur = time.monotonic() - t0
    got = [int(f["data"][:8], 16) for f in rx.frames()]
    ordered = all(b > a for a, b in zip(got, got[1:]))
    if scode != 0:
        record("raw", "burst-unpaced", "fail", "sender exit %s" % scode, s, r, dur)
    elif not got or not ordered:
        record("raw", "burst-unpaced", "fail", "%d frames, ordered=%s" % (len(got), ordered), s, r, dur)
    else:
        record("raw", "burst-unpaced", "pass", "%d of %d frames in order, %d lost (receiver socket buffer)" % (
            len(got), len(frames), len(frames) - len(got)), s, r, dur)


def suite_error_frames(caps, s, r):
    frames = frames_fixture("error")
    why = missing(caps[s], ["errorFramesTx"]) + ["receiver:" + m for m in missing(caps[r], ["errorFrames"])]
    if why:
        record("raw", "error-frames", "skip", "lacks " + ",".join(why), s, r)
        return
    t0 = time.monotonic()
    rx, scode, _ = transfer(s, r, frames, False, frames_file="/fixtures/frames/error.jsonl",
                            recv_extra=["--error-mask", ERROR_MASK])
    diff = compare_frames(frames, rx.frames()) if scode == 0 else "sender exit %s" % scode
    record("raw", "error-frames", "fail" if diff else "pass", diff or "%d error frames" % len(frames), s, r,
           time.monotonic() - t0)
    # Without an error mask the kernel delivers no error frames.
    rx, scode, _ = transfer(s, r, frames, False, frames_file="/fixtures/frames/error.jsonl",
                            count=1, timeout_ms=5000)
    ok = scode == 0 and rx.proc.returncode == 3 and not rx.frames()
    record("raw", "error-frames-masked", "pass" if ok else "fail",
           "no error frame without --error-mask" if ok else "receiver exit %s, %d frames" % (rx.proc.returncode, len(rx.frames())),
           s, r)


def kernel_match(frame, filters, join):
    """Linux CAN_RAW_FILTER semantics (net/can/af_can.c, raw.c)."""
    raw = frame["id"] | (CAN_EFF_FLAG if frame["extended"] else 0) | (CAN_RTR_FLAG if frame["remote"] else 0)
    hits = []
    for text in filters:
        parts = text.split(":")
        fid, mask = int(parts[0], 16), int(parts[1], 16)
        inv = "inv" in parts[2:]
        if "e" in parts[2:]:
            fid |= CAN_EFF_FLAG
            mask |= CAN_EFF_FLAG
        if "s" in parts[2:]:
            mask |= CAN_EFF_FLAG
        if mask & CAN_EFF_FLAG and not fid & CAN_EFF_FLAG:
            mask &= CAN_SFF_MASK | CAN_EFF_FLAG | CAN_RTR_FLAG
        m = (raw & mask) == (fid & mask)
        hits.append(not m if inv else m)
    return all(hits) if join else any(hits)


FILTER_CASES = [
    # name, filters, join, required features
    ("exact-standard", ["123:7FF:s"], False, []),
    ("exact-extended", ["12345678:1FFFFFFF:e"], False, []),
    ("any-format", ["123:7FF"], False, []),
    ("masked", ["100:700"], False, []),
    ("two-filters", ["7FF:7FF:s", "0:1FFFFFFF:e"], False, []),
    ("inverted", ["123:7FF:s:inv"], False, ["invertFilters"]),
    ("joined", ["0:0:s", "123:7FF:inv"], True, ["invertFilters", "joinFilters"]),
]


def suite_filters(caps, sender, receivers):
    frames = frames_fixture("standard") + frames_fixture("extended")
    for r in receivers:
        for name, filters, join, need in FILTER_CASES:
            why = missing(caps[r], ["filters"] + need)
            if why:
                record("raw", "filter-" + name, "skip", "lacks " + ",".join(why), sender, r)
                continue
            expected = [f for f in frames if kernel_match(f, filters, join)]
            extra = []
            for f in filters:
                extra += ["--filter", f]
            if join:
                extra.append("--join-filters")
            t0 = time.monotonic()
            # One frame more than expected: the receiver must time out with
            # exactly the expected frames.
            rx, scode, _ = transfer(sender, r, frames, False, recv_extra=extra,
                                    count=len(expected) + 1, timeout_ms=8000)
            dur = time.monotonic() - t0
            if scode != 0:
                record("raw", "filter-" + name, "fail", "sender/receiver failed: " + rx.error(), sender, r, dur)
                continue
            diff = compare_frames(expected, rx.frames())
            if rx.proc.returncode != 3:
                diff = diff or "receiver exit %d, want 3 (timeout after the expected frames)" % rx.proc.returncode
            record("raw", "filter-" + name, "fail" if diff else "pass",
                   diff or "%d of %d frames pass %s%s" % (len(expected), len(frames), " ".join(filters), " (joined)" if join else ""),
                   sender, r, dur)


def suite_multi(caps, sender, receivers):
    frames = frames_fixture("burst")[:500]
    path = write_work("multi.jsonl", frames)
    t0 = time.monotonic()
    rxs = [Background(r, ["receive", "--interface", VCAN, "--count", str(len(frames)), "--timeout-ms", "30000"])
           for r in receivers]
    if not all(rx.wait_ready() for rx in rxs):
        for rx in rxs:
            rx.finish(5)
        record("raw", "multi-consumer", "fail", "a receiver did not get ready", sender, "+".join(receivers))
        return
    code, _, _ = run(sender, ["send", "--interface", VCAN, "--gap-us", BURST_GAP_US, "--frames", path])
    bad = []
    for rx in rxs:
        rx.finish(60)
        diff = compare_frames(frames, rx.frames())
        if diff:
            bad.append("%s: %s" % (rx.adapter, diff))
    dur = time.monotonic() - t0
    if code != 0 or bad:
        record("raw", "multi-consumer", "fail", "; ".join(bad) or "sender exit %d" % code, sender, "+".join(receivers), dur)
    else:
        record("raw", "multi-consumer", "pass", "%d receivers x %d frames" % (len(rxs), len(frames)),
               sender, "+".join(receivers), dur)


def suite_loopback(caps, sender, receivers):
    r = next((x for x in ("pythoncan", "socketcanrs", "canutils", "scapy") if x in receivers and x != sender), None)
    if not caps[sender]["features"].get("disableLoopback"):
        record("raw", "no-loopback", "skip", "lacks disableLoopback", sender, r or "")
        return
    frames = frames_fixture("standard")[:3]
    t0 = time.monotonic()
    rx, scode, _ = transfer(sender, r, frames, False, send_extra=["--no-loopback"], count=1, timeout_ms=5000)
    got = rx.frames()
    ok = scode == 0 and rx.proc.returncode == 3 and not got
    record("raw", "no-loopback", "pass" if ok else "fail",
           "no frame reached another local socket" if ok else "sender %s, receiver exit %s, %d frames" % (scode, rx.proc.returncode, len(got)),
           sender, r, time.monotonic() - t0)


def suite_recv_own(caps, sender):
    if not caps[sender]["features"].get("recvOwn"):
        record("raw", "recv-own", "skip", "lacks recvOwn", sender, sender)
        return
    frames = frames_fixture("standard")
    t0 = time.monotonic()
    code, docs, err = run(sender, ["send", "--interface", VCAN, "--recv-own", "--frames", "/fixtures/frames/standard.jsonl"])
    got = [d["frame"] for d in docs if d.get("type") == "frame"]
    diff = compare_frames(frames, got) if code == 0 else "exit %d: %s" % (code, docs[-1] if docs else err[-200:])
    record("raw", "recv-own", "fail" if diff else "pass", diff or "%d own frames echoed" % len(got), sender, sender,
           time.monotonic() - t0)


MALFORMED = [
    ("classical-len-9", {"id": 0x123, "len": 9, "data": "000102030405060708"}),
    ("fd-len-9", {"id": 0x123, "fd": True, "len": 9, "data": "000102030405060708"}),
    ("standard-id-0x800", {"id": 0x800, "len": 0, "data": ""}),
    ("extended-id-0x20000000", {"id": 0x20000000, "extended": True, "len": 0, "data": ""}),
    ("len-mismatch", {"id": 0x123, "len": 4, "data": "0011"}),
    ("brs-on-classical", {"id": 0x123, "brs": True, "len": 0, "data": ""}),
    ("remote-fd", {"id": 0x123, "fd": True, "remote": True, "len": 0, "data": ""}),
]


def suite_malformed(caps, sender):
    for name, doc in MALFORMED:
        path = write_work("bad-%s.jsonl" % name, [doc])
        code, docs, _ = run(sender, ["send", "--interface", VCAN, "--fd", "--frames", path])
        err = docs[-1] if docs else {}
        ok = code == 2 and err.get("type") == "error"
        record("raw", "malformed-" + name, "pass" if ok else "fail",
               "rejected: " + err.get("message", "") if ok else "exit %d, %s" % (code, err), sender, "")


def suite_capture_replay(caps, sender, receivers):
    capturers = [a for a in caps if "capture" in caps[a]["operations"]]
    players = [a for a in caps if "replay" in caps[a]["operations"]]
    check = next((x for x in ("socketcanrs", "pythoncan", "canutils") if x in receivers), None)
    if not sender or not check:
        return
    for fixture, fd in (("standard", False), ("fd", True)):
        frames = frames_fixture(fixture)
        for c in capturers:
            if fd and not caps[c]["features"].get("fd"):
                record("raw", "capture-" + fixture, "skip", "lacks fd", sender, c)
                continue
            log = "capture-%s-%s.log" % (c, fixture)
            cargs = ["capture", "--interface", VCAN, "--count", str(len(frames)), "--timeout-ms", "20000",
                     "--output", "/work/" + log] + (["--fd"] if fd else [])
            cap = Background(c, cargs)
            if not cap.wait_ready():
                cap.finish(5)
                record("raw", "capture-" + fixture, "fail", "not ready: " + cap.error(), sender, c)
                continue
            run(sender, ["send", "--interface", VCAN, "--frames", "/fixtures/frames/%s.jsonl" % fixture] + (["--fd"] if fd else []))
            code = cap.finish(40)
            if code != 0:
                record("raw", "capture-" + fixture, "fail", "capture exit %d: %s" % (code, cap.error()), sender, c)
                continue
            record("raw", "capture-" + fixture, "pass", "%d frames into a candump log" % len(frames), sender, c)
            for p in players:
                if fd and not caps[p]["features"].get("fd"):
                    record("raw", "replay-" + fixture, "skip", "lacks fd", p, check)
                    continue
                t0 = time.monotonic()
                rx = Background(check, ["receive", "--interface", VCAN, "--count", str(len(frames)), "--timeout-ms", "20000"]
                                + (["--fd"] if fd else []))
                if not rx.wait_ready():
                    rx.finish(5)
                    record("raw", "replay-" + fixture, "fail", "receiver not ready", p, check)
                    continue
                pcode, pdocs, _ = run(p, ["replay", "--interface", VCAN, "--input", "/work/" + log] + (["--fd"] if fd else []))
                rx.finish(40)
                diff = compare_frames(frames, rx.frames()) if pcode == 0 else "replay exit %d: %s" % (pcode, pdocs[-1:] )
                record("raw", "replay-" + fixture, "fail" if diff else "pass",
                       diff or "log of %s replayed, %d frames" % (c, len(frames)), p, check, time.monotonic() - t0)


def ip(*args):
    if ADMIN == "none":
        return False
    cmd = (shlex.split(ADMIN) if ADMIN else []) + ["ip", "link"] + list(args)
    return subprocess.run(cmd, capture_output=True).returncode == 0


def suite_interfaces(caps, sender, receivers):
    for r in receivers:
        code, docs, _ = run(r, ["receive", "--interface", "vcan-missing", "--timeout-ms", "1000"])
        err = docs[-1] if docs else {}
        ok = code == 4 and err.get("code") == "interface"
        record("raw", "interface-missing", "pass" if ok else "fail",
               "exit 4: " + err.get("message", "") if ok else "exit %d %s" % (code, err), "", r)
    if ADMIN == "none":
        for r in receivers:
            record("raw", "interface-down", "skip", "ADMIN=none: cannot change interfaces", "", r)
        return
    for r in receivers:
        t0 = time.monotonic()
        rx = Background(r, ["receive", "--interface", VCAN2, "--count", "5", "--timeout-ms", "15000"])
        if not rx.wait_ready():
            rx.finish(5)
            record("raw", "interface-down", "fail", "not ready", "", r)
            continue
        if not ip("set", VCAN2, "down"):
            rx.finish(20)
            record("raw", "interface-down", "skip", "cannot set %s down" % VCAN2, "", r)
            continue
        code = rx.finish(20)
        took = time.monotonic() - t0
        ip("set", VCAN2, "up")
        ok = code in (1, 4) and took < 12
        record("raw", "interface-down", "pass" if ok else "fail",
               ("receive ended with exit %d after the interface went down: %s" % (code, rx.error()[:120])) if ok
               else "exit %d after %.1fs (want 1 or 4, promptly)" % (code, took), "", r, took)
        # The interface works again after the restart.
        if sender:
            frames = frames_fixture("standard")[:5]
            rx2, scode, _ = transfer(sender, r, frames, False, interface=VCAN2, timeout_ms=10000)
            diff = compare_frames(frames, rx2.frames()) if scode == 0 else "sender exit %s" % scode
            record("raw", "interface-restart", "fail" if diff else "pass", diff or "frames flow again after up",
                   sender, r)


# ── ISO-TP ──────────────────────────────────────────────────────────────────

ISOTP_CASES = [
    # name, payload args, extra args (sender's view), features
    ("sf-1", ["--size", "1"], [], []),
    ("sf-7", ["--size", "7"], [], []),
    ("ff-8", ["--size", "8"], [], []),
    ("mf-100", ["--size", "100"], [], []),
    ("mf-4095", ["--size", "4095"], [], []),
    # STmin 1 ms: at STmin 0 a userspace receiver (python-can-isotp) cannot
    # always keep up with 700 consecutive frames and the kernel drops some
    # from its socket buffer (wrong sequence number); see LIMITATIONS.md.
    ("ff-escape-5000", ["--size", "5000"], ["--stmin", "01"], []),
    ("bs-2", ["--size", "300"], ["--bs", "2"], []),
    ("bs-1-stmin-5ms", ["--size", "120"], ["--bs", "1", "--stmin", "05"], []),
    ("stmin-300us", ["--size", "200"], ["--stmin", "F3"], []),
    ("padding", ["--size", "20"], ["--padding", "CC"], []),
    ("three-messages", ["--size", "50", "--count", "3"], [], []),
    ("extended-addressing", ["--size", "100"], ["--addressing", "extended", "--tx-ext", "55", "--rx-ext", "AA"],
     ["isotpExtendedAddressing"]),
    ("mixed-addressing", ["--size", "100"], ["--addressing", "mixed", "--tx-ext", "33", "--rx-ext", "33"],
     ["isotpMixedAddressing"]),
    ("29-bit-ids", ["--size", "100"], ["--extended-ids", "--tx-id", "18DA10F1", "--rx-id", "18DAF110"],
     ["isotpExtendedIds"]),
    ("fd-sf-escape-50", ["--size", "50"], ["--fd", "--tx-dl", "64"], ["isotpFD"]),
    ("fd-mf-1000", ["--size", "1000"], ["--fd", "--tx-dl", "64"], ["isotpFD"]),
    ("fd-mf-5000", ["--size", "5000"], ["--fd", "--tx-dl", "64", "--stmin", "01"], ["isotpFD"]),
]


def receiver_view(extra):
    """The receiver's flags: identifiers and address bytes swapped."""
    out = list(extra)
    tx = rx = None
    if "--tx-id" in out:
        tx = out[out.index("--tx-id") + 1]
        rx = out[out.index("--rx-id") + 1]
    else:
        tx, rx = "7E0", "7E8"
        out += ["--tx-id", tx, "--rx-id", rx]
    out[out.index("--tx-id") + 1], out[out.index("--rx-id") + 1] = rx, tx
    if "--tx-ext" in out:
        a, b = out.index("--tx-ext") + 1, out.index("--rx-ext") + 1
        out[a], out[b] = out[b], out[a]
    return out


def sender_view(extra):
    out = list(extra)
    if "--tx-id" not in out:
        out += ["--tx-id", "7E0", "--rx-id", "7E8"]
    # BS and STmin are what the receiver sends in its flow control.
    for flag in ("--bs", "--stmin"):
        if flag in out:
            i = out.index(flag)
            del out[i:i + 2]
    return out


def payload(args):
    size = int(args[args.index("--size") + 1])
    return bytes(i % 251 for i in range(size)).hex()


def kernel_has_isotp():
    try:
        import socket
        socket.socket(socket.PF_CAN, socket.SOCK_DGRAM, socket.CAN_ISOTP).close()
        return True
    except (OSError, AttributeError):
        return False


# Adapters whose ISO-TP is the kernel's CAN_ISOTP.
KERNEL_ISOTP = {"canutils"}


def suite_isotp(caps):
    senders = [a for a in caps if "isotp-send" in caps[a]["operations"]]
    receivers = [a for a in caps if "isotp-receive" in caps[a]["operations"]]
    if not kernel_has_isotp():
        for a in sorted(KERNEL_ISOTP & set(senders + receivers)):
            record("isotp", "kernel-isotp", "skip", "the kernel of this host has no CAN_ISOTP (can-isotp module)", a, a)
        senders = [a for a in senders if a not in KERNEL_ISOTP]
        receivers = [a for a in receivers if a not in KERNEL_ISOTP]
    for name, pargs, extra, need in ISOTP_CASES:
        count = int(pargs[pargs.index("--count") + 1]) if "--count" in pargs else 1
        for s in senders:
            for r in receivers:
                why = missing(caps[s], need) + ["receiver:" + m for m in missing(caps[r], need)]
                if why:
                    record("isotp", name, "skip", "lacks " + ",".join(why), s, r)
                    continue
                t0 = time.monotonic()
                rargs = ["isotp-receive", "--interface", VCAN, "--count", str(count), "--timeout-ms", "20000"]
                rx = Background(r, rargs + receiver_view(extra))
                if not rx.wait_ready():
                    code = rx.finish(5)
                    err = rx.error()
                    status = "skip" if code == 2 and "unsupported" in json.dumps(rx.docs) else "fail"
                    record("isotp", name, status, "receiver: " + err, s, r)
                    continue
                scode, sdocs, serr = run(s, ["isotp-send", "--interface", VCAN, "--timeout-ms", "15000"]
                                         + pargs + sender_view(extra), timeout=60)
                rx.finish(30)
                dur = time.monotonic() - t0
                msgs = rx.messages()
                want = payload(pargs)
                if scode == 2 and sdocs and sdocs[-1].get("code") == "unsupported":
                    record("isotp", name, "skip", "sender: " + sdocs[-1].get("message", ""), s, r, dur)
                elif scode != 0:
                    record("isotp", name, "fail", "sender exit %d: %s" % (scode, sdocs[-1:] or serr[-200:]), s, r, dur)
                elif len(msgs) != count or any(m.get("data") != want for m in msgs):
                    record("isotp", name, "fail", "received %d of %d messages intact; %s" % (
                        sum(m.get("data") == want for m in msgs), count, rx.error()), s, r, dur)
                else:
                    record("isotp", name, "pass", "%d x %d bytes" % (count, len(want) // 2), s, r, dur)

    # Negative: no receiver, so no flow control: the sender must give up.
    for s in senders:
        t0 = time.monotonic()
        code, docs, _ = run(s, ["isotp-send", "--interface", VCAN2, "--size", "100", "--tx-id", "6F0",
                                "--rx-id", "6F8", "--timeout-ms", "10000"], timeout=60)
        dur = time.monotonic() - t0
        ok = code in (1, 3)
        record("isotp", "no-flow-control", "pass" if ok else "fail",
               "sender failed with exit %d after %.1fs: %s" % (code, dur, docs[-1].get("message", "") if docs else "")
               if ok else "exit %d" % code, s, "(none)", dur)

    raw = next((a for a in ("pythoncan", "socketcanrs", "canutils") if a in caps), None)
    if raw:
        suite_isotp_injected(caps, raw, receivers)


def suite_isotp_injected(caps, raw, receivers):
    """ISO-TP receivers fed hand-made frames by a raw-CAN adapter."""
    data = bytes(range(20))

    def fr(hexdata):
        b = bytes.fromhex(hexdata)
        return {"id": 0x7E0, "len": len(b), "data": b.hex()}

    ff = fr("1014" + data[:6].hex())
    cases = [
        ("injected-valid", [ff, fr("21" + data[6:13].hex()), fr("22" + data[13:20].hex())], True),
        ("injected-wrong-sn", [ff, fr("22" + data[6:13].hex()), fr("23" + data[13:20].hex())], False),
        ("injected-cf-without-ff", [fr("21" + data[6:13].hex())], False),
        ("injected-sf-len-0", [fr("00")], False),
    ]
    for r in receivers:
        for name, frames, deliver in cases:
            rx = Background(r, ["isotp-receive", "--interface", VCAN, "--tx-id", "7E8", "--rx-id", "7E0",
                                "--count", "1", "--timeout-ms", "4000"])
            if not rx.wait_ready():
                rx.finish(5)
                record("isotp", name, "fail", "receiver not ready", raw, r)
                continue
            path = write_work("inject-%s.jsonl" % name, frames)
            run(raw, ["send", "--interface", VCAN, "--gap-us", "20000", "--frames", path])
            code = rx.finish(20)
            msgs = rx.messages()
            if deliver:
                ok = code == 0 and len(msgs) == 1 and msgs[0]["data"] == data.hex()
                detail = "message delivered" if ok else "exit %d, %d messages" % (code, len(msgs))
            else:
                ok = code == 3 and not msgs
                detail = "nothing delivered" if ok else "exit %d, messages %s" % (code, msgs)
            record("isotp", name, "pass" if ok else "fail", detail, raw, r)


# ── DBC ─────────────────────────────────────────────────────────────────────

def known_differences():
    known = {}
    path = os.path.join(ROOT, "tests", "known-differences.tsv")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    cols = line.rstrip("\n").split("\t")
                    known[tuple(cols[:4])] = cols[4] if len(cols) > 4 else ""
    return known


def approx(a, b):
    if a is None or b is None or isinstance(a, str) or isinstance(b, str):
        return a == b
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def suite_dbc(caps):
    oracles = [a for a in ("cantools", "canmatrix") if a in caps and "decode" in caps[a]["operations"]]
    if len(oracles) < 2:
        record("dbc", "agreement", "skip", "needs cantools and canmatrix")
        return
    known = known_differences()
    a, b = oracles
    dbcdir = os.path.join(ROOT, "fixtures", "dbc")
    for name in sorted(os.listdir(dbcdir)):
        if not name.endswith(".dbc"):
            continue
        base = name[:-4]
        db = "/fixtures/dbc/" + name
        frames_file = os.path.join(dbcdir, base + ".frames.jsonl")
        if os.path.exists(frames_file):
            outs = {}
            for o in oracles:
                code, docs, err = run(o, ["decode", "--db", db, "--frames", "/fixtures/dbc/%s.frames.jsonl" % base])
                outs[o] = (code, docs, err)
            compare_decoded(base, outs, a, b, known)
        msgs_file = os.path.join(dbcdir, base + ".messages.jsonl")
        if os.path.exists(msgs_file):
            outs = {}
            for o in oracles:
                code, docs, err = run(o, ["encode", "--db", db, "--messages", "/fixtures/dbc/%s.messages.jsonl" % base])
                outs[o] = (code, docs, err)
            compare_encoded(base, outs, a, b, known)
    suite_kcd(caps, known)


def suite_kcd(caps, known):
    """canmatrix reads the KCD fixtures directly and converts them to DBC;
    cantools decodes with the converted DBC. Both decodings must agree."""
    if "canmatrix" not in caps or "cantools" not in caps or "convert" not in caps["canmatrix"]["operations"]:
        record("dbc", "kcd", "skip", "needs canmatrix (convert) and cantools")
        return
    kcddir = os.path.join(ROOT, "fixtures", "kcd")
    for name in sorted(os.listdir(kcddir)):
        if not name.endswith(".kcd"):
            continue
        base = name[:-4]
        out = "kcd-%s-%s.dbc" % (base, uuid.uuid4().hex[:6])
        code, docs, err = run("canmatrix", ["convert", "--input", "/fixtures/kcd/" + name, "--output", "/work/" + out])
        if code != 0:
            record("dbc", "kcd-convert-" + base, "fail", "exit %d: %s" % (code, docs[-1:] or err[-200:]), "canmatrix", "")
            continue
        record("dbc", "kcd-convert-" + base, "pass", "KCD converted to DBC", "canmatrix", "")
        frames = "/fixtures/kcd/%s.frames.jsonl" % base
        outs = {"canmatrix": run("canmatrix", ["decode", "--db", "/fixtures/kcd/" + name, "--frames", frames]),
                "cantools": run("cantools", ["decode", "--db", "/work/" + out, "--frames", frames])}
        compare_decoded("kcd-" + base, outs, "cantools", "canmatrix", known)


def compare_decoded(base, outs, a, b, known):
    (ca, da, ea), (cb, db_, eb) = outs[a], outs[b]
    if ca != 0 or cb != 0:
        record("dbc", "decode-" + base, "fail", "%s exit %d %s; %s exit %d %s" % (a, ca, ea[-150:], b, cb, eb[-150:]), a, b)
        return
    da = [d for d in da if d.get("type") in ("decoded", "decode-error")]
    db_ = [d for d in db_ if d.get("type") in ("decoded", "decode-error")]
    if len(da) != len(db_):
        record("dbc", "decode-" + base, "fail", "%d vs %d results" % (len(da), len(db_)), a, b)
        return
    diffs, accepted, checked = [], [], 0
    for x, y in zip(da, db_):
        msg = x.get("message") or "0x%X" % x.get("id", 0)
        if x["type"] != y["type"]:
            key = (base, msg, "*", "type")
            (accepted if key in known else diffs).append("%s: %s vs %s" % (msg, x["type"], y["type"]))
            continue
        if x["type"] != "decoded":
            continue
        sx, sy = x.get("signals", {}), y.get("signals", {})
        for sig in sorted(set(sx) | set(sy)):
            vx, vy = sx.get(sig), sy.get(sig)
            for field in ("raw", "physical", "label"):
                checked += 1
                ax = vx.get(field) if vx else None
                ay = vy.get(field) if vy else None
                same = approx(ax, ay) if field == "physical" and ax is not None and ay is not None else ax == ay
                if not same:
                    key = (base, msg, sig, field)
                    text = "%s.%s %s: %s=%r %s=%r" % (msg, sig, field, a, ax, b, ay)
                    (accepted if key in known else diffs).append(text)
    status = "fail" if diffs else ("known" if accepted else "pass")
    detail = "; ".join(diffs[:4]) if diffs else ("%d values agree; known differences: %s" % (checked, "; ".join(accepted[:3]))
                                                 if accepted else "%d values agree" % checked)
    record("dbc", "decode-" + base, status, detail, a, b)


def compare_encoded(base, outs, a, b, known):
    (ca, da, ea), (cb, db_, eb) = outs[a], outs[b]
    if ca != 0 or cb != 0:
        record("dbc", "encode-" + base, "fail", "%s exit %d %s; %s exit %d %s" % (a, ca, ea[-150:], b, cb, eb[-150:]), a, b)
        return
    da = [d for d in da if d.get("type") in ("encoded", "encode-error")]
    db_ = [d for d in db_ if d.get("type") in ("encoded", "encode-error")]
    diffs, accepted = [], []
    for x, y in zip(da, db_):
        msg = x.get("message")
        same = x.get("type") == y.get("type") and (x.get("type") != "encoded" or
                                                   (x.get("data") == y.get("data") and x.get("id") == y.get("id")))
        if not same:
            key = (base, msg, "*", "encode")
            (accepted if key in known else diffs).append("%s: %s=%s %s=%s" % (
                msg, a, x.get("data", x.get("error")), b, y.get("data", y.get("error"))))
    if len(da) != len(db_):
        diffs.append("%d vs %d results" % (len(da), len(db_)))
    status = "fail" if diffs else ("known" if accepted else "pass")
    record("dbc", "encode-" + base, status,
           "; ".join(diffs[:4]) or ("%d messages agree" % len(da)) + (("; known: " + "; ".join(accepted[:3])) if accepted else ""),
           a, b)


# ── report ──────────────────────────────────────────────────────────────────

def report(caps, outdir, started):
    os.makedirs(outdir, exist_ok=True)
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    versions = {}
    for a in caps:
        code, docs, _ = run(a, ["print-version"])
        versions[a] = docs[0] if docs else {}
    doc = {"schemaVersion": "1.0", "started": started, "kernel": os.uname().release,
           "images": {a: image(a) for a in caps}, "versions": versions,
           "capabilities": caps, "counts": counts, "results": results}
    os.makedirs(os.path.join(outdir, "documents"), exist_ok=True)
    for a, docs in DOCS.items():
        with open(os.path.join(outdir, "documents", a + ".jsonl"), "w") as f:
            for d in docs:
                f.write(json.dumps(d) + "\n")
    for a in caps:
        with open(os.path.join(outdir, "documents", a + ".capabilities.json"), "w") as f:
            f.write(json.dumps(caps[a]) + "\n")
        with open(os.path.join(outdir, "documents", a + ".version.json"), "w") as f:
            f.write(json.dumps(versions[a]) + "\n")
    with open(os.path.join(outdir, "selftest.json"), "w") as f:
        json.dump(doc, f, indent=1)
    with open(os.path.join(outdir, "selftest.md"), "w") as f:
        f.write("# canbus-interop self-test\n\n")
        f.write("Kernel %s, started %s. %s\n\n" % (os.uname().release, started,
                ", ".join("%d %s" % (v, k) for k, v in sorted(counts.items()))))
        f.write("| Suite | Scenario | Sender | Receiver | Result | Detail |\n|---|---|---|---|---|---|\n")
        for r in results:
            f.write("| %s | %s | %s | %s | %s | %s |\n" % (r["suite"], r["scenario"], r["sender"], r["receiver"],
                                                          r["status"], r["detail"].replace("|", "\\|")[:200]))
    print("\n%s  (reports in %s)" % (", ".join("%d %s" % (v, k) for k, v in sorted(counts.items())), outdir))
    return counts.get("fail", 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", default=os.environ.get("REPORTS", os.path.join(ROOT, "reports")))
    args = ap.parse_args()
    adapters = os.environ.get("ADAPTERS", " ".join(ALL_ADAPTERS)).split()
    suites = os.environ.get("SUITES", "raw isotp dbc").split()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    caps = {a: capabilities(a) for a in adapters}
    if "raw" in suites:
        suite_raw(caps)
    if "isotp" in suites:
        suite_isotp(caps)
    if "dbc" in suites:
        suite_dbc(caps)
    failed = report(caps, args.reports, started)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
