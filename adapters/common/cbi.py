# SPDX-License-Identifier: MIT
"""Shared command line, documents and exit codes of the Python adapters.

Implements the parts of docs/CONTAINER_CONTRACT.md that do not depend on a
stack: argument parsing, the JSON documents, error handling and exit codes.
Every CAN operation is done by the adapter's upstream stack; nothing here
touches a CAN socket.
"""

import argparse
import json
import os
import sys
import time

SCHEMA_VERSION = "1.0"

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_TIMEOUT = 3
EXIT_ENV = 4

ALL_OPERATIONS = [
    "send", "receive", "capture", "replay", "decode", "encode",
    "isotp-send", "isotp-receive", "convert", "log-convert",
]

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_INV_FILTER = 0x20000000
CAN_SFF_MASK = 0x7FF
CAN_EFF_MASK = 0x1FFFFFFF

FD_LENGTHS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64]

_CODES = {
    EXIT_FAILURE: "io",
    EXIT_USAGE: "usage",
    EXIT_TIMEOUT: "timeout",
    EXIT_ENV: "interface",
}


class AdapterError(Exception):
    """An error that ends the operation with an error document."""

    def __init__(self, exit_code, code, message):
        super().__init__(message)
        self.exit_code = exit_code
        self.code = code
        self.message = message


def usage(message):
    return AdapterError(EXIT_USAGE, "usage", message)


def unsupported(message):
    return AdapterError(EXIT_USAGE, "unsupported", message)


def timeout(message):
    return AdapterError(EXIT_TIMEOUT, "timeout", message)


def io_error(message):
    return AdapterError(EXIT_FAILURE, "io", message)


def protocol_error(message):
    return AdapterError(EXIT_FAILURE, "protocol", message)


def interface_error(message):
    return AdapterError(EXIT_ENV, "interface", message)


def emit(doc):
    """Write one JSON document as one line on stdout and flush it."""
    sys.stdout.write(json.dumps(doc, separators=(",", ":"), sort_keys=False) + "\n")
    sys.stdout.flush()


def log(message):
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def event(kind, **fields):
    doc = {"schemaVersion": SCHEMA_VERSION, "type": kind}
    doc.update(fields)
    return doc


def ready():
    emit(event("ready"))


def frame_event(doc):
    emit(event("frame", frame=doc))


def result(operation, **fields):
    doc = {"schemaVersion": SCHEMA_VERSION, "type": "result", "operation": operation}
    doc.update(fields)
    return doc


def check_interface(name):
    """Fail with exit 4 when the interface is missing or down."""
    base = "/sys/class/net/" + name
    if not os.path.isdir(base):
        raise interface_error("interface %s does not exist" % name)
    try:
        with open(base + "/operstate") as f:
            state = f.read().strip()
        with open(base + "/flags") as f:
            flags = int(f.read().strip(), 16)
    except OSError as e:
        raise interface_error("interface %s: %s" % (name, e))
    if not flags & 0x1 or state == "down":
        raise interface_error("interface %s is down" % name)


def interface_mtu(name):
    try:
        with open("/sys/class/net/%s/mtu" % name) as f:
            return int(f.read().strip())
    except OSError:
        return 0


# ── Frame documents ─────────────────────────────────────────────────────────

def frame_doc(can_id, extended=False, fd=False, brs=False, esi=False,
              remote=False, error=False, length=0, data=b"",
              timestamp=None, interface=None):
    doc = {
        "id": int(can_id),
        "extended": bool(extended),
        "fd": bool(fd),
        "brs": bool(brs),
        "esi": bool(esi),
        "remote": bool(remote),
        "error": bool(error),
        "len": int(length),
        "data": bytes(data).hex(),
    }
    if timestamp is not None:
        doc["timestamp"] = "%.6f" % timestamp
    if interface:
        doc["interface"] = interface
    return doc


class Frame:
    """A validated frame document."""

    __slots__ = ("id", "extended", "fd", "brs", "esi", "remote", "error", "len", "data")

    def __init__(self, doc):
        if not isinstance(doc, dict):
            raise usage("frame document is not an object")
        try:
            self.id = int(doc["id"])
        except (KeyError, TypeError, ValueError):
            raise usage("frame document without a valid id: %r" % (doc,))
        self.extended = bool(doc.get("extended", False))
        self.fd = bool(doc.get("fd", False))
        self.brs = bool(doc.get("brs", False))
        self.esi = bool(doc.get("esi", False))
        self.remote = bool(doc.get("remote", False))
        self.error = bool(doc.get("error", False))
        try:
            self.data = bytes.fromhex(doc.get("data", ""))
        except ValueError:
            raise usage("frame data is not hex: %r" % doc.get("data"))
        self.len = int(doc.get("len", len(self.data)))
        if self.error and (self.extended or self.fd or self.remote):
            raise usage("an error frame is neither extended, FD nor remote")
        limit = CAN_EFF_MASK if self.extended or self.error else CAN_SFF_MASK
        if self.id < 0 or self.id > limit:
            raise usage("identifier 0x%X out of range" % self.id)
        if self.fd:
            if self.remote:
                raise usage("CAN FD frames have no remote form")
            if self.len not in FD_LENGTHS:
                raise usage("CAN FD length %d is not a valid FD length" % self.len)
        else:
            if self.brs or self.esi:
                raise usage("BRS/ESI only exist on CAN FD frames")
            if self.len > 8:
                raise usage("classical CAN length %d > 8" % self.len)
        if self.remote:
            if self.data:
                raise usage("remote frame with data")
        elif len(self.data) != self.len:
            raise usage("len %d does not match %d data bytes" % (self.len, len(self.data)))

    def doc(self, **meta):
        return frame_doc(self.id, self.extended, self.fd, self.brs, self.esi,
                         self.remote, self.error, self.len, self.data, **meta)


def read_json_lines(path):
    """Yield the JSON documents of a JSON Lines file ("-" = stdin)."""
    stream = sys.stdin if path in (None, "-") else open(path)
    try:
        for n, line in enumerate(stream, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                yield json.loads(line)
            except ValueError as e:
                raise usage("%s:%d: %s" % (path or "-", n, e))
    finally:
        if stream is not sys.stdin:
            stream.close()


def read_frames(path):
    return [Frame(d) for d in read_json_lines(path)]


# ── Filters ─────────────────────────────────────────────────────────────────

class Filter:
    """A --filter value: <id>:<mask>[:e|:s][:inv], identifier and mask in hex.

    raw_id and raw_mask are the values of struct can_filter (Linux
    CAN_RAW_FILTER), with CAN_EFF_FLAG and CAN_INV_FILTER as the kernel
    expects them.
    """

    def __init__(self, text):
        parts = text.split(":")
        if len(parts) < 2:
            raise usage("filter %r: want <id>:<mask>[:e|:s][:inv]" % text)
        try:
            self.id = int(parts[0], 16)
            self.mask = int(parts[1], 16)
        except ValueError:
            raise usage("filter %r: id and mask are hex" % text)
        self.format = None
        self.invert = False
        for p in parts[2:]:
            if p in ("e", "s"):
                self.format = p
            elif p == "inv":
                self.invert = True
            else:
                raise usage("filter %r: unknown modifier %r" % (text, p))
        self.raw_id = self.id
        self.raw_mask = self.mask
        if self.format == "e":
            self.raw_id |= CAN_EFF_FLAG
            self.raw_mask |= CAN_EFF_FLAG
        elif self.format == "s":
            self.raw_mask |= CAN_EFF_FLAG
        if self.invert:
            self.raw_id |= CAN_INV_FILTER


# ── Command line ────────────────────────────────────────────────────────────

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise usage(message)


def _hex(text):
    try:
        return int(text, 16)
    except ValueError:
        raise argparse.ArgumentTypeError("not hex: %r" % text)


def build_parser(adapter):
    p = _Parser(prog="canbus-interop", description="canbus-interop adapter " + adapter)
    sub = p.add_subparsers(dest="command")

    sub.add_parser("print-capabilities")
    sub.add_parser("print-version")
    pf = sub.add_parser("print-fixture")
    pf.add_argument("path")

    def common(sp, count=False):
        sp.add_argument("--interface", default="vcan0")
        sp.add_argument("--fd", action="store_true")
        sp.add_argument("--timeout-ms", type=int, default=5000)
        if count:
            sp.add_argument("--count", type=int, default=1)

    s = sub.add_parser("send")
    common(s)
    s.add_argument("--frames", default="-")
    s.add_argument("--gap-us", type=int, default=0)
    s.add_argument("--recv-own", action="store_true")
    s.add_argument("--no-loopback", action="store_true")

    for name in ("receive", "capture"):
        r = sub.add_parser(name)
        common(r, count=True)
        r.add_argument("--filter", action="append", default=[], type=Filter)
        r.add_argument("--join-filters", action="store_true")
        r.add_argument("--error-mask", type=_hex, default=0)
        if name == "capture":
            r.add_argument("--output", required=True)

    rp = sub.add_parser("replay")
    common(rp)
    rp.add_argument("--input", required=True)

    d = sub.add_parser("decode")
    d.add_argument("--db", required=True)
    d.add_argument("--frames", default="-")
    e = sub.add_parser("encode")
    e.add_argument("--db", required=True)
    e.add_argument("--messages", default="-")
    e.add_argument("--raw", action="store_true")

    c = sub.add_parser("convert")
    c.add_argument("--input", required=True)
    c.add_argument("--output", required=True)

    lc = sub.add_parser("log-convert")
    lc.add_argument("--input", required=True)
    lc.add_argument("--output", required=True)

    for name in ("isotp-send", "isotp-receive"):
        t = sub.add_parser(name)
        common(t, count=True)
        t.add_argument("--tx-id", type=_hex, required=True)
        t.add_argument("--rx-id", type=_hex, required=True)
        t.add_argument("--extended-ids", action="store_true")
        t.add_argument("--addressing", choices=["normal", "extended", "mixed"], default="normal")
        t.add_argument("--tx-ext", type=_hex)
        t.add_argument("--rx-ext", type=_hex)
        t.add_argument("--tx-dl", type=int, default=8)
        t.add_argument("--bs", type=int, default=0)
        t.add_argument("--stmin", type=_hex, default=0)
        t.add_argument("--padding", type=_hex)
        if name == "isotp-send":
            g = t.add_mutually_exclusive_group(required=True)
            g.add_argument("--data")
            g.add_argument("--size", type=int)
    return p


def isotp_payload(args):
    if args.data is not None:
        try:
            return bytes.fromhex(args.data)
        except ValueError:
            raise usage("--data is not hex")
    if args.size < 1:
        raise usage("--size must be at least 1")
    return bytes(i % 251 for i in range(args.size))


def check_isotp_args(args, caps):
    f = caps["features"]
    if args.fd and not f.get("isotpFD"):
        raise unsupported("ISO-TP over CAN FD")
    if args.addressing == "extended" and not f.get("isotpExtendedAddressing"):
        raise unsupported("ISO-TP extended addressing")
    if args.addressing == "mixed" and not f.get("isotpMixedAddressing"):
        raise unsupported("ISO-TP mixed addressing")
    if args.extended_ids and not f.get("isotpExtendedIds"):
        raise unsupported("ISO-TP with 29-bit identifiers")
    if args.addressing != "normal" and (args.tx_ext is None or args.rx_ext is None):
        raise usage("--addressing %s needs --tx-ext and --rx-ext" % args.addressing)
    if args.tx_dl not in (8, 12, 16, 20, 24, 32, 48, 64):
        raise usage("--tx-dl must be 8, 12, 16, 20, 24, 32, 48 or 64")
    if args.tx_dl > 8 and not args.fd:
        raise usage("--tx-dl > 8 needs --fd")
    if not 0 <= args.bs <= 255 or not 0 <= args.stmin <= 255:
        raise usage("--bs and --stmin are bytes")


def check_receive_args(args, caps):
    f = caps["features"]
    if args.fd and not f.get("fd"):
        raise unsupported("CAN FD")
    if args.filter and not f.get("filters"):
        raise unsupported("filters")
    if any(x.invert for x in args.filter) and not f.get("invertFilters"):
        raise unsupported("inverted filters")
    if args.join_filters and not f.get("joinFilters"):
        raise unsupported("joined filters")
    if args.error_mask and not f.get("errorFrames"):
        raise unsupported("error frames")


def check_send_frames(frames, args, caps):
    f = caps["features"]
    if getattr(args, "recv_own", False) and not f.get("recvOwn"):
        raise unsupported("receive own messages")
    if getattr(args, "no_loopback", False) and not f.get("disableLoopback"):
        raise unsupported("disabling local loopback")
    for fr in frames:
        if fr.fd and not args.fd:
            raise usage("CAN FD frame without --fd")
        if fr.fd and not f.get("fd"):
            raise unsupported("CAN FD")
        if fr.brs and not f.get("brs"):
            raise unsupported("BRS")
        if fr.esi and not f.get("esi"):
            raise unsupported("transmitting ESI")
        if fr.remote and not f.get("remote"):
            raise unsupported("remote frames")
        if fr.error and not f.get("errorFramesTx"):
            raise unsupported("transmitting error frames")


class Deadline:
    def __init__(self, timeout_ms):
        self.end = time.monotonic() + timeout_ms / 1000.0

    def remaining(self):
        return max(0.0, self.end - time.monotonic())

    def expired(self):
        return time.monotonic() >= self.end


def run(adapter, capabilities, version, handlers):
    """Parse the command line and run the handler; never returns."""
    caps = {"schemaVersion": SCHEMA_VERSION, "adapter": adapter}
    caps.update(capabilities)
    caps["operations"] = [op for op in ALL_OPERATIONS if op in handlers]
    try:
        argv = sys.argv[1:] or ["print-capabilities"]
        if argv[0] in ALL_OPERATIONS and argv[0] not in handlers:
            # Before the flags: an unsupported operation is reported as such,
            # not as a usage error about its required flags.
            raise unsupported("operation %s is not supported by %s" % (argv[0], adapter))
        args = build_parser(adapter).parse_args(argv)
        cmd = args.command
        if cmd == "print-capabilities":
            emit(caps)
        elif cmd == "print-version":
            doc = {"schemaVersion": SCHEMA_VERSION, "adapter": adapter}
            doc.update(version)
            emit(doc)
        elif cmd == "print-fixture":
            path = os.path.normpath(os.path.join("/fixtures", args.path))
            if not path.startswith("/fixtures/") or not os.path.isfile(path):
                raise usage("no fixture %s" % args.path)
            with open(path, "rb") as f:
                sys.stdout.buffer.write(f.read())
            sys.stdout.flush()
        elif cmd not in handlers:
            raise unsupported("operation %s is not supported by %s" % (cmd, adapter))
        else:
            if cmd in ("receive", "capture"):
                check_receive_args(args, caps)
            if cmd in ("isotp-send", "isotp-receive"):
                check_isotp_args(args, caps)
            if cmd in ("send", "receive", "capture", "replay", "isotp-send", "isotp-receive"):
                if args.timeout_ms <= 0:
                    raise usage("--timeout-ms must be positive")
                check_interface(args.interface)
                if args.fd and interface_mtu(args.interface) < 72:
                    raise interface_error("interface %s is not CAN FD capable (mtu < 72)" % args.interface)
            handlers[cmd](args, caps)
        sys.exit(EXIT_OK)
    except AdapterError as e:
        emit({"schemaVersion": SCHEMA_VERSION, "type": "error", "code": e.code, "message": e.message})
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        sys.exit(EXIT_FAILURE)
    except BrokenPipeError:
        sys.exit(EXIT_FAILURE)
    except Exception as e:  # an upstream stack failed in a way not foreseen
        log("%s: %s: %s" % (adapter, type(e).__name__, e))
        emit({"schemaVersion": SCHEMA_VERSION, "type": "error", "code": "io",
              "message": "%s: %s" % (type(e).__name__, e)})
        sys.exit(EXIT_FAILURE)
