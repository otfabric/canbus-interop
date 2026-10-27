# SPDX-License-Identifier: MIT
"""canbus-interop adapter for Scapy's native CAN socket (scapy.contrib.cansocket_native)."""

import os
import select
import time

from scapy.config import conf

conf.contribs.setdefault("CAN", {})
conf.contribs["CAN"]["remove-padding"] = True
conf.contribs["CAN"].setdefault("swap-bytes", False)

from scapy.contrib.cansocket_native import NativeCANSocket  # noqa: E402
from scapy.layers.can import CAN, CANFD  # noqa: E402
import scapy  # noqa: E402

import cbi  # noqa: E402

ADAPTER = "scapy"

CAPABILITIES = {
    "features": {
        "fd": True,
        "brs": True,
        "esi": True,
        "remote": True,
        # NativeCANSocket has no parameter for CAN_RAW_ERR_FILTER, so it
        # never receives error frames.
        "errorFrames": False,
        "errorFramesTx": True,
        "filters": True,
        # can_filters are packed into struct can_filter as given: the
        # kernel's CAN_INV_FILTER bit passes through.
        "invertFilters": True,
        "joinFilters": False,
        "recvOwn": True,
        "disableLoopback": False,
    },
}

VERSION = {
    "upstream": "scapy",
    "repository": "https://github.com/secdev/scapy",
    "version": scapy.VERSION,
    "revision": os.environ.get("UPSTREAM_REVISION", ""),
    "license": "GPL-2.0-only",
    "language": "Python",
}


def open_socket(args, filters=None, recv_own=False):
    can_filters = None
    if filters:
        can_filters = [{"can_id": f.raw_id, "can_mask": f.raw_mask} for f in filters]
    try:
        return NativeCANSocket(channel=args.interface, fd=args.fd,
                               receive_own_messages=recv_own, can_filters=can_filters)
    except OSError as e:
        raise cbi.interface_error("%s: %s" % (args.interface, e))


def to_packet(fr):
    flags = []
    if fr.error:
        flags.append("error")
    if fr.extended:
        flags.append("extended")
    if fr.remote:
        flags.append("remote_transmission_request")
    if fr.fd:
        fd_flags = ["fd_frame"]
        if fr.brs:
            fd_flags.append("bit_rate_switch")
        if fr.esi:
            fd_flags.append("error_state_indicator")
        return CANFD(flags="+".join(flags) or 0, identifier=fr.id, length=fr.len,
                     fd_flags="+".join(fd_flags), data=fr.data)
    return CAN(flags="+".join(flags) or 0, identifier=fr.id, length=fr.len,
               data=b"" if fr.remote else fr.data)


def from_packet(pkt, interface):
    flags = pkt.flags
    remote = bool(flags.remote_transmission_request)
    error = bool(flags.error)
    fd = isinstance(pkt, CANFD)
    brs = esi = False
    if fd:
        brs = bool(pkt.fd_flags.bit_rate_switch)
        esi = bool(pkt.fd_flags.error_state_indicator)
    data = b"" if remote else bytes(pkt.data)[:pkt.length]
    return cbi.frame_doc(pkt.identifier, extended=bool(flags.extended) and not error,
                         fd=fd, brs=brs, esi=esi, remote=remote, error=error,
                         length=pkt.length, data=data,
                         timestamp=float(pkt.time) if pkt.time else None,
                         interface=interface)


def receive_one(sock, deadline):
    r, _, _ = select.select([sock.ins], [], [], deadline.remaining())
    if not r:
        return None
    pkt = sock.recv()
    if pkt is None:
        # NativeCANSocket.recv_raw swallows OSError (interface down) and
        # returns nothing although the socket was readable.
        raise cbi.io_error("receive failed (interface down?)")
    return pkt


def op_send(args, caps):
    frames = cbi.read_frames(args.frames)
    cbi.check_send_frames(frames, args, caps)
    sock = open_socket(args, recv_own=args.recv_own)
    echoed = 0
    try:
        for fr in frames:
            sock.send(to_packet(fr))
            if args.gap_us:
                time.sleep(args.gap_us / 1e6)
        if args.recv_own:
            deadline = cbi.Deadline(args.timeout_ms)
            while echoed < len(frames):
                pkt = receive_one(sock, deadline)
                if pkt is None:
                    break
                cbi.frame_event(from_packet(pkt, args.interface))
                echoed += 1
    finally:
        sock.close()
    if args.recv_own:
        cbi.emit(cbi.result("send", sent=len(frames), echoed=echoed))
        if echoed < len(frames):
            raise cbi.timeout("%d of %d own frames echoed" % (echoed, len(frames)))
    else:
        cbi.emit(cbi.result("send", sent=len(frames)))


def op_receive(args, caps):
    sock = open_socket(args, args.filter)
    received = 0
    try:
        cbi.ready()
        deadline = cbi.Deadline(args.timeout_ms)
        while received < args.count and not deadline.expired():
            pkt = receive_one(sock, deadline)
            if pkt is None:
                break
            cbi.frame_event(from_packet(pkt, args.interface))
            received += 1
    finally:
        sock.close()
    complete = received >= args.count
    cbi.emit(cbi.result("receive", received=received, complete=complete))
    if not complete:
        raise cbi.timeout("received %d of %d" % (received, args.count))


if __name__ == "__main__":
    cbi.run(ADAPTER, CAPABILITIES, VERSION, {
        "send": op_send,
        "receive": op_receive,
    })
