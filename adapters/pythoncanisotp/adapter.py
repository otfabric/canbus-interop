# SPDX-License-Identifier: MIT
"""canbus-interop adapter for python-can-isotp: ISO 15765-2 in userspace.

The ISO-TP state machine (segmentation, flow control, STmin, timeouts) is
python-can-isotp's own; frames go through python-can's socketcan interface.
"""

import os
import time

import can
import isotp

import cbi

ADAPTER = "pythoncanisotp"

CAPABILITIES = {
    "features": {
        "isotpFD": True,
        "isotpExtendedAddressing": True,
        # Mixed addressing with 11-bit identifiers only: python-can-isotp's
        # Mixed_29bits uses the fixed 0x18CE/0x18CD identifiers of ISO
        # 15765-2 and cannot take --tx-id/--rx-id.
        "isotpMixedAddressing": True,
        "isotpExtendedIds": True,
    },
}

VERSION = {
    "upstream": "python-can-isotp",
    "repository": "https://github.com/pylessard/python-can-isotp",
    "version": isotp.__version__ if hasattr(isotp, "__version__") else "2.0.7",
    "revision": os.environ.get("UPSTREAM_REVISION", ""),
    "license": "MIT",
    "language": "Python",
    "transport": "python-can %s (socketcan)" % can.__version__,
}

MAX_SIZE = 1 << 20


def address(args):
    M = isotp.AddressingMode
    if args.addressing == "normal":
        mode = M.Normal_29bits if args.extended_ids else M.Normal_11bits
        return isotp.Address(mode, txid=args.tx_id, rxid=args.rx_id)
    if args.addressing == "extended":
        mode = M.Extended_29bits if args.extended_ids else M.Extended_11bits
        return isotp.Address(mode, txid=args.tx_id, rxid=args.rx_id,
                             target_address=args.tx_ext, source_address=args.rx_ext)
    if args.extended_ids:
        raise cbi.unsupported("mixed addressing with 29-bit identifiers takes fixed identifiers in python-can-isotp")
    if args.tx_ext != args.rx_ext:
        raise cbi.unsupported("python-can-isotp mixed addressing uses one address extension for both directions")
    return isotp.Address(M.Mixed_11bits, txid=args.tx_id, rxid=args.rx_id,
                         address_extension=args.tx_ext)


class Stack:
    def __init__(self, args):
        self.errors = []
        try:
            self.bus = can.Bus(interface="socketcan", channel=args.interface, fd=args.fd)
        except OSError as e:
            raise cbi.interface_error("%s: %s" % (args.interface, e))
        params = {
            "stmin": args.stmin,
            "blocksize": args.bs,
            "tx_data_length": args.tx_dl,
            "tx_padding": args.padding,
            "can_fd": args.fd,
            "bitrate_switch": False,
            "max_frame_size": MAX_SIZE,
            "blocking_send": True,
            "rx_flowcontrol_timeout": 1000,
            "rx_consecutive_frame_timeout": 1000,
        }
        if args.tx_dl > 8:
            params["tx_data_min_length"] = 8
        self.stack = isotp.CanStack(self.bus, address=address(args), params=params,
                                    error_handler=self.errors.append)
        self.stack.start()

    def close(self):
        try:
            self.stack.stop()
        finally:
            self.bus.shutdown()


def op_isotp_send(args, caps):
    payload = cbi.isotp_payload(args)
    deadline = cbi.Deadline(args.timeout_ms)
    st = Stack(args)
    try:
        for _ in range(args.count):
            try:
                st.stack.send(payload, send_timeout=max(0.01, deadline.remaining()))
            except isotp.BlockingSendTimeout as e:
                raise cbi.timeout("isotp send: %s" % e)
            except isotp.BlockingSendFailure as e:
                raise cbi.protocol_error("isotp send: %s; %s" % (e, "; ".join(map(str, st.errors))))
    finally:
        st.close()
    cbi.emit(cbi.result("isotp-send", sent=args.count))


def op_isotp_receive(args, caps):
    deadline = cbi.Deadline(args.timeout_ms)
    st = Stack(args)
    received = 0
    try:
        cbi.ready()
        while received < args.count and not deadline.expired():
            data = st.stack.recv(block=True, timeout=min(0.2, max(0.001, deadline.remaining())))
            if data is None:
                continue
            cbi.emit(cbi.event("message", len=len(data), data=bytes(data).hex()))
            received += 1
        time.sleep(0.05)  # let the last flow control frame leave
    finally:
        st.close()
    complete = received >= args.count
    cbi.emit(cbi.result("isotp-receive", received=received, complete=complete))
    if not complete:
        detail = "; ".join(map(str, st.errors))
        raise cbi.timeout("received %d of %d%s" % (received, args.count, (": " + detail) if detail else ""))


if __name__ == "__main__":
    cbi.run(ADAPTER, CAPABILITIES, VERSION, {
        "isotp-send": op_isotp_send,
        "isotp-receive": op_isotp_receive,
    })
