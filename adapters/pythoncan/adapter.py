# SPDX-License-Identifier: MIT
"""canbus-interop adapter for python-can (socketcan and slcan interfaces)."""

import os
import struct
import time

import can

import cbi

ADAPTER = "pythoncan"

CAPABILITIES = {
    "features": {
        "fd": True,
        "brs": True,
        "esi": True,
        "remote": True,
        "errorFrames": True,
        "errorFramesTx": True,
        "filters": True,
        # python-can packs can_id/can_mask into struct can_filter as given, so
        # the kernel's CAN_INV_FILTER bit passes through it.
        "invertFilters": True,
        # python-can has no API for CAN_RAW_JOIN_FILTERS.
        "joinFilters": False,
        "recvOwn": True,
        "disableLoopback": True,
        # log-convert: python-can's own readers and writers of these
        # formats. What survives a round trip per format is in
        # docs/LOG_FORMATS.md (BLF: everything; ASC, TRC, CSV: lossy).
        "logAsc": True,
        "logBlf": True,
        "logTrc": True,
        "logCsv": True,
        # (1.2) send/receive on --interface slcan:<pyserial URL> with
        # python-can's slcan interface (pyserial 3.5).
        "slcan": True,
    },
}

VERSION = {
    "upstream": "python-can",
    "repository": "https://github.com/hardbyte/python-can",
    "version": can.__version__,
    "revision": os.environ.get("UPSTREAM_REVISION", ""),
    "license": "LGPL-3.0-only",
    "language": "Python",
}

CAN_RAW_ERR_FILTER = 2
SOL_CAN_RAW = 101


def open_bus(args, filters=None, recv_own=False, loopback=True):
    if cbi.is_slcan(args.interface):
        # python-can's slcan sends "C", "S6", "" and "O" on open and "C"
        # on shutdown; sleep_after_open=0: the peer is no USB device.
        kwargs = dict(interface="slcan", channel=args.interface[len(cbi.SLCAN_PREFIX):],
                      bitrate=500000, sleep_after_open=0)
    else:
        kwargs = dict(interface="socketcan", channel=args.interface, fd=args.fd,
                      receive_own_messages=recv_own, local_loopback=loopback)
    if filters:
        kwargs["can_filters"] = [{"can_id": f.raw_id, "can_mask": f.raw_mask} for f in filters]
    try:
        return can.Bus(**kwargs)
    except (OSError, can.CanInitializationError) as e:
        raise cbi.interface_error("%s: %s" % (args.interface, e))


def to_message(fr):
    return can.Message(
        arbitration_id=fr.id,
        is_extended_id=fr.extended,
        is_remote_frame=fr.remote,
        is_error_frame=fr.error,
        is_fd=fr.fd,
        bitrate_switch=fr.brs,
        error_state_indicator=fr.esi,
        dlc=fr.len,
        data=None if fr.remote else fr.data,
    )


def from_message(msg):
    data = b"" if msg.is_remote_frame else bytes(msg.data)
    length = msg.dlc if msg.is_remote_frame or msg.is_error_frame else len(data)
    if msg.is_error_frame:
        data = bytes(msg.data)
        length = len(data)
    return cbi.frame_doc(
        msg.arbitration_id, extended=msg.is_extended_id and not msg.is_error_frame,
        fd=msg.is_fd, brs=msg.bitrate_switch, esi=msg.error_state_indicator,
        remote=msg.is_remote_frame, error=msg.is_error_frame, length=length,
        data=data, timestamp=msg.timestamp, interface=msg.channel)


def op_send(args, caps):
    frames = cbi.read_frames(args.frames)
    cbi.check_send_frames(frames, args, caps)
    bus = open_bus(args, recv_own=args.recv_own, loopback=not args.no_loopback)
    sent = 0
    echoed = 0
    try:
        for fr in frames:
            try:
                bus.send(to_message(fr), timeout=max(0.001, cbi.Deadline(args.timeout_ms).remaining()))
            except can.CanError as e:
                raise cbi.io_error("send: %s" % e)
            sent += 1
            if args.gap_us:
                time.sleep(args.gap_us / 1e6)
        if args.recv_own:
            deadline = cbi.Deadline(args.timeout_ms)
            while echoed < sent and not deadline.expired():
                msg = bus.recv(timeout=deadline.remaining())
                if msg is None:
                    break
                if not msg.is_rx:
                    cbi.frame_event(from_message(msg))
                    echoed += 1
    finally:
        bus.shutdown()
    if args.recv_own:
        cbi.emit(cbi.result("send", sent=sent, echoed=echoed))
        if echoed < sent:
            raise cbi.timeout("%d of %d own frames echoed" % (echoed, sent))
    else:
        cbi.emit(cbi.result("send", sent=sent))


def _receive(args, on_message):
    bus = open_bus(args, args.filter)
    try:
        if not cbi.is_slcan(args.interface):
            # python-can enables all error classes; apply the requested mask.
            bus.socket.setsockopt(SOL_CAN_RAW, CAN_RAW_ERR_FILTER, struct.pack("=I", args.error_mask))
        cbi.ready()
        deadline = cbi.Deadline(args.timeout_ms)
        received = 0
        while received < args.count and not deadline.expired():
            msg = bus.recv(timeout=deadline.remaining())
            if msg is None:
                break
            if msg.is_fd and not args.fd:
                continue
            on_message(msg)
            received += 1
    finally:
        bus.shutdown()
    return received


def finish(operation, received, count):
    complete = received >= count
    cbi.emit(cbi.result(operation, received=received, complete=complete))
    if not complete:
        raise cbi.timeout("received %d of %d" % (received, count))


def op_receive(args, caps):
    n = _receive(args, lambda m: cbi.frame_event(from_message(m)))
    finish("receive", n, args.count)


def op_capture(args, caps):
    writer = can.CanutilsLogWriter(args.output, channel=args.interface)
    try:
        n = _receive(args, writer.on_message_received)
    finally:
        writer.stop()
    finish("capture", n, args.count)


def op_replay(args, caps):
    bus = open_bus(args)
    sent = 0
    try:
        for msg in can.CanutilsLogReader(args.input):
            if msg.is_error_frame:
                continue
            if msg.is_fd and not args.fd:
                raise cbi.usage("the log has CAN FD frames: use --fd")
            msg.channel = None
            bus.send(msg)
            sent += 1
    finally:
        bus.shutdown()
    cbi.emit(cbi.result("replay", sent=sent))


# log-convert: files go through python-can's LogReader/Logger, chosen by
# extension; .jsonl is the contract's frame documents (lossless), so a
# consumer sees exactly what python-can read or will write.
LOG_EXTENSIONS = (".log", ".asc", ".blf", ".trc", ".csv", ".jsonl")


def _ext(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in LOG_EXTENSIONS:
        raise cbi.usage("%s: unsupported log format %r (one of %s)" % (path, ext, ", ".join(LOG_EXTENSIONS)))
    return ext


def _read_log(path):
    if _ext(path) == ".jsonl":
        for doc in cbi.read_json_lines(path):
            fr = cbi.Frame(doc)
            msg = to_message(fr)
            if "timestamp" in doc:
                msg.timestamp = float(doc["timestamp"])
            yield msg
        return
    kwargs = {}
    if _ext(path) == ".asc":
        # Absolute times: the Begin Triggerblock date plus each offset.
        kwargs["relative_timestamp"] = False
    for msg in can.LogReader(path, **kwargs):
        yield msg


def op_log_convert(args, caps):
    out_ext = _ext(args.output)
    msgs = _read_log(args.input)
    n = 0
    try:
        if out_ext == ".jsonl":
            import json
            with open(args.output, "w") as f:
                for msg in msgs:
                    doc = from_message(msg)
                    doc.pop("interface", None)
                    f.write(json.dumps(doc) + "\n")
                    n += 1
        else:
            with can.Logger(args.output) as w:
                for msg in msgs:
                    w.on_message_received(msg)
                    n += 1
    except cbi.AdapterError:
        raise
    except Exception as e:
        raise cbi.io_error("log-convert: %s: %s" % (type(e).__name__, e))
    cbi.emit(cbi.result("log-convert", input=args.input, output=args.output, frames=n))


if __name__ == "__main__":
    cbi.run(ADAPTER, CAPABILITIES, VERSION, {
        "send": op_send,
        "receive": op_receive,
        "capture": op_capture,
        "replay": op_replay,
        "log-convert": op_log_convert,
    })
