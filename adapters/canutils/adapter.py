# SPDX-License-Identifier: MIT
"""canbus-interop adapter for linux-can/can-utils.

Every CAN operation runs one of the upstream programs: cansend, candump,
canplayer (CAN_RAW) and isotpsend, isotprecv (the kernel's CAN_ISOTP). This
module builds their command lines and turns their output into the documents
of the container contract.
"""

import os
import select
import signal
import subprocess
import time

import cbi

ADAPTER = "canutils"

CAPABILITIES = {
    "features": {
        "fd": True,
        "brs": True,
        "esi": True,
        "remote": True,
        "errorFrames": True,
        # cansend writes an 8-digit identifier with CAN_ERR_FLAG as given:
        # error frames can be injected on vcan.
        "errorFramesTx": True,
        "filters": True,
        "invertFilters": True,
        "joinFilters": True,
        # candump never sets CAN_RAW_RECV_OWN_MSGS and cansend never reads.
        "recvOwn": False,
        "disableLoopback": False,
        "isotpFD": True,
        "isotpExtendedAddressing": True,
        # The kernel puts the address extension of mixed addressing in the
        # first data byte, like extended addressing (CAN_ISOTP_EXTEND_ADDR).
        "isotpMixedAddressing": True,
        "isotpExtendedIds": True,
    },
}

VERSION = {
    "upstream": "linux-can/can-utils",
    "repository": "https://github.com/linux-can/can-utils",
    "version": os.environ.get("UPSTREAM_VERSION", ""),
    "revision": os.environ.get("UPSTREAM_REVISION", ""),
    "license": "GPL-2.0-only OR BSD-3-Clause",
    "language": "C",
    "isotp": "Linux kernel CAN_ISOTP (%s)" % os.uname().release,
}


# ── candump/cansend frame syntax (can-utils lib.c) ──────────────────────────

def cansend_text(fr):
    if fr.error:
        return "%08X#" % (fr.id | cbi.CAN_ERR_FLAG) + fr.data.hex().upper()
    ident = "%08X" % fr.id if fr.extended else "%03X" % fr.id
    if fr.remote:
        return ident + "#R" + ("%X" % fr.len if fr.len else "")
    if fr.fd:
        flags = (1 if fr.brs else 0) | (2 if fr.esi else 0)
        return ident + "##%X" % flags + fr.data.hex().upper()
    return ident + "#" + fr.data.hex().upper()


def parse_frame_text(text, timestamp=None, interface=None):
    ident, sep, rest = text.partition("#")
    if not sep:
        raise cbi.protocol_error("candump: no '#' in %r" % text)
    value = int(ident, 16)
    error = len(ident) == 8 and bool(value & cbi.CAN_ERR_FLAG)
    extended = len(ident) == 8 and not error
    can_id = value & cbi.CAN_EFF_MASK
    if rest.startswith("#"):
        flags = int(rest[1], 16)
        data = bytes.fromhex(rest[2:])
        return cbi.frame_doc(can_id, extended, True, bool(flags & 1), bool(flags & 2),
                             False, False, len(data), data, timestamp, interface)
    if rest[:1] in ("R", "r"):
        length = int(rest[1], 16) if len(rest) > 1 else 0
        return cbi.frame_doc(can_id, extended, remote=True, length=length,
                             timestamp=timestamp, interface=interface)
    data = bytes.fromhex(rest.split("_")[0])
    return cbi.frame_doc(can_id, extended, error=error, length=len(data), data=data,
                         timestamp=timestamp, interface=interface)


def parse_log_line(line):
    """A candump log line: (seconds.micros) interface frame [direction]."""
    parts = line.split()
    if len(parts) < 3 or not parts[0].startswith("("):
        raise cbi.protocol_error("candump: unexpected line %r" % line)
    ts = float(parts[0].strip("()"))
    return parse_frame_text(parts[2], ts, parts[1])


def candump_filters(args):
    tokens = []
    for f in args.filter:
        raw_id = f.raw_id & ~cbi.CAN_INV_FILTER
        # candump sets CAN_EFF_FLAG itself for an 8-digit identifier.
        text = "%08X" % raw_id if raw_id & cbi.CAN_EFF_FLAG else "%X" % raw_id
        tokens.append(text + ("~" if f.invert else ":") + "%X" % f.raw_mask)
    if args.join_filters:
        tokens.append("j")
    if args.error_mask:
        tokens.append("#%08X" % args.error_mask)
    return ",".join([args.interface] + tokens)


# ── readiness ───────────────────────────────────────────────────────────────

def _receivers(interface):
    """Receivers registered on the interface (rows of /proc/net/can/rcvlist_*)."""
    n = 0
    base = "/proc/net/can"
    for name in os.listdir(base):
        if not name.startswith("rcvlist_"):
            continue
        try:
            with open(os.path.join(base, name)) as f:
                for row in f:
                    if interface in row.split():
                        n += 1
        except OSError:
            pass
    return n


def wait_registered(proc, interface, before, deadline):
    """Wait until proc has bound its socket: a new CAN receiver appears."""
    while not deadline.expired():
        if proc.poll() is not None:
            raise cbi.io_error("%s exited with %d" % (proc.args[0], proc.returncode))
        if _receivers(interface) > before:
            return
        time.sleep(0.01)
    raise cbi.timeout("%s did not bind its socket" % proc.args[0])


def stop(proc):
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


# ── operations ──────────────────────────────────────────────────────────────

def run_tool(argv, deadline, stdin=None):
    try:
        p = subprocess.run(argv, input=stdin, capture_output=True, text=True,
                           timeout=max(0.1, deadline.remaining()))
    except subprocess.TimeoutExpired:
        raise cbi.timeout("%s timed out" % argv[0])
    if p.returncode != 0:
        raise cbi.io_error("%s: exit %d: %s" % (argv[0], p.returncode,
                                                (p.stderr or p.stdout).strip()))
    return p.stdout


def op_send(args, caps):
    frames = cbi.read_frames(args.frames)
    cbi.check_send_frames(frames, args, caps)
    deadline = cbi.Deadline(args.timeout_ms)
    for fr in frames:
        run_tool(["cansend", args.interface, cansend_text(fr)], deadline)
        if args.gap_us:
            time.sleep(args.gap_us / 1e6)
    cbi.emit(cbi.result("send", sent=len(frames)))


def _candump(args, logfile):
    deadline = cbi.Deadline(args.timeout_ms)
    before = _receivers(args.interface)
    argv = ["candump", "-n", str(args.count), "-f", logfile, candump_filters(args)]
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    ended = False
    try:
        wait_registered(proc, args.interface, before, deadline)
        cbi.ready()
        try:
            proc.wait(max(0.0, deadline.remaining()))
            ended = True
        except subprocess.TimeoutExpired:
            pass
    finally:
        stop(proc)
    if ended and proc.returncode != 0:
        # candump ends by itself before the count only on an error, for
        # example when the interface goes down.
        message = "candump: exit %d: %s" % (proc.returncode, proc.stderr.read().strip())
        if "down" in message:
            raise cbi.interface_error(message)
        raise cbi.io_error(message)
    frames = []
    with open(logfile) as f:
        for line in f:
            if line.strip():
                doc = parse_log_line(line.strip())
                # candump always enables CAN_RAW_FD_FRAMES; a socket without
                # --fd would not have received FD frames.
                if doc["fd"] and not args.fd:
                    continue
                frames.append(doc)
    return frames


def finish(operation, received, count):
    complete = received >= count
    cbi.emit(cbi.result(operation, received=received, complete=complete))
    if not complete:
        raise cbi.timeout("received %d of %d" % (received, count))


def op_receive(args, caps):
    logfile = "/tmp/candump-%d.log" % os.getpid()
    try:
        frames = _candump(args, logfile)
    finally:
        if os.path.exists(logfile):
            os.unlink(logfile)
    for doc in frames:
        cbi.frame_event(doc)
    finish("receive", len(frames), args.count)


def op_capture(args, caps):
    frames = _candump(args, args.output)
    finish("capture", len(frames), args.count)


def op_replay(args, caps):
    interfaces = set()
    sent = 0
    with open(args.input) as f:
        for line in f:
            if line.strip():
                parts = line.split()
                doc = parse_log_line(line.strip())
                if doc["fd"] and not args.fd:
                    raise cbi.usage("the log has CAN FD frames: use --fd")
                interfaces.add(parts[1])
                sent += 1
    argv = ["canplayer", "-I", args.input, "-t"]
    argv += ["%s=%s" % (args.interface, i) for i in sorted(interfaces)]
    run_tool(argv, cbi.Deadline(args.timeout_ms))
    cbi.emit(cbi.result("replay", sent=sent))


def isotp_argv(tool, args):
    fmt = "%08X" if args.extended_ids else "%03X"
    argv = [tool, "-s", fmt % args.tx_id, "-d", fmt % args.rx_id]
    if args.addressing != "normal":
        argv += ["-x", "%02X:%02X" % (args.tx_ext, args.rx_ext)]
    if args.padding is not None:
        argv += ["-p", "%02X:" % args.padding]
    if args.fd:
        argv += ["-L", "72:%d:0" % args.tx_dl]
    return argv


def op_isotp_send(args, caps):
    payload = cbi.isotp_payload(args)
    deadline = cbi.Deadline(args.timeout_ms)
    argv = isotp_argv("isotpsend", args) + ["-b", args.interface]
    text = " ".join("%02X" % b for b in payload) + "\n"
    for _ in range(args.count):
        try:
            run_tool(argv, deadline, stdin=text)
        except cbi.AdapterError as e:
            if e.code == "io":
                raise cbi.protocol_error(e.message)
            raise
    cbi.emit(cbi.result("isotp-send", sent=args.count))


def op_isotp_receive(args, caps):
    deadline = cbi.Deadline(args.timeout_ms)
    argv = ["stdbuf", "-oL"] + isotp_argv("isotprecv", args)
    argv += ["-b", "%X" % args.bs, "-m", "%X" % args.stmin, "-l", args.interface]
    before = _receivers(args.interface)
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    received = 0
    try:
        wait_registered(proc, args.interface, before, deadline)
        cbi.ready()
        fd = proc.stdout.fileno()
        buf = b""
        while received < args.count and not deadline.expired():
            r, _, _ = select.select([fd], [], [], min(0.1, deadline.remaining()))
            if not r:
                if proc.poll() is not None:
                    break
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf and received < args.count:
                line, buf = buf.split(b"\n", 1)
                data = bytes.fromhex(line.decode().replace(" ", ""))
                if not data:
                    # isotprecv prints an empty line when read() fails: the
                    # kernel reported a broken reception (wrong sequence
                    # number, timeout). ISO-TP has no empty messages.
                    cbi.log("isotprecv: reception failed (empty line)")
                    continue
                cbi.emit(cbi.event("message", len=len(data), data=data.hex()))
                received += 1
    finally:
        stop(proc)
    finish("isotp-receive", received, args.count)


if __name__ == "__main__":
    cbi.run(ADAPTER, CAPABILITIES, VERSION, {
        "send": op_send,
        "receive": op_receive,
        "capture": op_capture,
        "replay": op_replay,
        "isotp-send": op_isotp_send,
        "isotp-receive": op_isotp_receive,
    })
