# SPDX-License-Identifier: MIT
"""canbus-interop adapter for canmatrix: DBC decode/encode oracle and KCD conversion."""

import decimal
import logging
import math
import os
import struct

import canmatrix
import canmatrix.formats

import cbi

ADAPTER = "canmatrix"

CAPABILITIES = {
    "features": {
        "dbcMultiplexing": True,
        # canmatrix decodes extended multiplexing but its Frame.encode raises
        # EncodingComplexMultiplexed: encode of such messages is unsupported.
        "dbcExtendedMultiplexing": True,
        "dbcFD": True,
        "dbcFloat": True,
        "encodeRaw": True,
        # AUTOSAR 4 ARXML system descriptions (fixtures/arxml): I-SIGNAL-I-PDUs
        # in CAN frames, LINEAR/TEXTTABLE/SCALE_LINEAR_AND_TEXTTABLE/IDENTICAL
        # compu methods, 2C base types, CAN FD. Neither applies a PDU's
        # START-POSITION inside its frame (see docs/FIXTURES.md).
        "arxml": True,
    },
}

VERSION = {
    "upstream": "canmatrix",
    "repository": "https://github.com/ebroecker/canmatrix",
    "version": getattr(canmatrix, "__version__", "1.3.3"),
    "revision": os.environ.get("UPSTREAM_REVISION", ""),
    "license": "BSD-2-Clause",
    "language": "Python",
}

# canmatrix logs every length mismatch and range violation as a warning.
logging.disable(logging.WARNING)


def load(path):
    try:
        dbs = canmatrix.formats.loadp(path)
    except Exception as e:
        raise cbi.usage("%s: %s" % (path, e))
    if not dbs:
        raise cbi.usage("%s: no database" % path)
    return dbs.get("") or next(iter(dbs.values()))


def raw_text(signal, value):
    if signal.is_float:
        if signal.size == 32:
            return str(struct.unpack("<I", struct.pack("<f", float(value)))[0])
        return str(struct.unpack("<Q", struct.pack("<d", float(value)))[0])
    return str(int(value))


def number(v):
    """JSON for a physical value; NaN and infinities as "nan", "inf", "-inf"."""
    if isinstance(v, decimal.Decimal):
        if v.is_finite() and v == v.to_integral_value() and abs(v) < 2 ** 63:
            return int(v)
        v = float(v)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return str(v)
    return v


def op_decode(args, caps):
    db = load(args.db)
    for doc in cbi.read_json_lines(args.frames):
        fr = cbi.Frame(doc)
        frame = db.frame_by_id(canmatrix.ArbitrationId(id=fr.id, extended=fr.extended))
        if frame is None or frame.arbitration_id.extended != fr.extended:
            cbi.emit(cbi.event("decode-error", id=fr.id, extended=fr.extended,
                               error="no message with this identifier"))
            continue
        try:
            decoded = frame.decode(bytes(fr.data))
        except Exception as e:
            cbi.emit(cbi.event("decode-error", id=fr.id, extended=fr.extended,
                               error="%s: %s" % (type(e).__name__, e)))
            continue
        signals = {}
        for name, ds in decoded.items():
            entry = {"raw": raw_text(ds.signal, ds.raw_value), "physical": number(ds.phys_value)}
            named = ds.named_value
            if isinstance(named, str):
                entry["label"] = named
            signals[name] = entry
        cbi.emit(cbi.event("decoded", id=fr.id, extended=fr.extended, message=frame.name, signals=signals))


def op_encode(args, caps):
    db = load(args.db)
    for doc in cbi.read_json_lines(args.messages):
        name = doc.get("message")
        frame = db.frame_by_name(name)
        if frame is None:
            cbi.emit(cbi.event("encode-error", message=name, error="no such message"))
            continue
        try:
            # Frame.encode packs raw values (a string is looked up in the
            # value table); physical values go through canmatrix's own
            # Signal.phys2raw, in decimal arithmetic.
            values = {}
            for k, v in doc.get("signals", {}).items():
                sig = frame.signal_by_name(k)
                if sig is None:
                    raise KeyError("no signal %s" % k)
                if args.raw:
                    values[k] = int(v)
                else:
                    values[k] = sig.phys2raw(decimal.Decimal(str(v)))
            data = frame.encode(values)
        except Exception as e:
            cbi.emit(cbi.event("encode-error", message=name, error="%s: %s" % (type(e).__name__, e)))
            continue
        cbi.emit(cbi.event("encoded", message=name, id=frame.arbitration_id.id,
                           extended=bool(frame.arbitration_id.extended), data=bytes(data).hex()))


def op_convert(args, caps):
    try:
        dbs = canmatrix.formats.loadp(args.input)
        if len(dbs) == 1:
            # One bus: exactly the requested file (canmatrix names the file
            # of each bus <output>_<bus> otherwise).
            dbs = {"": next(iter(dbs.values()))}
        canmatrix.formats.dumpp(dbs, args.output)
    except Exception as e:
        raise cbi.io_error("convert: %s: %s" % (type(e).__name__, e))
    cbi.emit(cbi.result("convert", input=args.input, output=args.output,
                        messages=sum(len(d.frames) for d in dbs.values())))


if __name__ == "__main__":
    cbi.run(ADAPTER, CAPABILITIES, VERSION, {
        "decode": op_decode,
        "encode": op_encode,
        "convert": op_convert,
    })
