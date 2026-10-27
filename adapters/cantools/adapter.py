# SPDX-License-Identifier: MIT
"""canbus-interop adapter for cantools: DBC decode and encode oracle."""

import math
import os
import struct

import cantools

import cbi

ADAPTER = "cantools"

CAPABILITIES = {
    "features": {
        "dbcMultiplexing": True,
        "dbcExtendedMultiplexing": True,
        "dbcFD": True,
        "dbcFloat": True,
        "encodeRaw": True,
    },
}

VERSION = {
    "upstream": "cantools",
    "repository": "https://github.com/cantools/cantools",
    "version": cantools.__version__,
    "revision": os.environ.get("UPSTREAM_REVISION", ""),
    "license": "MIT",
    "language": "Python",
}


def load(path):
    try:
        return cantools.database.load_file(path)
    except Exception as e:  # cantools raises many types on a bad database
        raise cbi.usage("%s: %s" % (path, e))


def raw_text(signal, value):
    """The raw value as an exact decimal string (floats: their bit pattern)."""
    if signal.is_float:
        if signal.length == 32:
            return str(struct.unpack("<I", struct.pack("<f", value))[0])
        return str(struct.unpack("<Q", struct.pack("<d", value))[0])
    return str(int(value))


def number(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return str(v)
    if isinstance(v, float) and v.is_integer() and abs(v) < 2 ** 53:
        return int(v)
    return v


def lookup(db, fr):
    try:
        msg = db.get_message_by_frame_id(fr.id)
    except KeyError:
        return None
    if msg.is_extended_frame != fr.extended:
        return None
    return msg


def op_decode(args, caps):
    db = load(args.db)
    for doc in cbi.read_json_lines(args.frames):
        fr = cbi.Frame(doc)
        msg = lookup(db, fr)
        if msg is None:
            cbi.emit(cbi.event("decode-error", id=fr.id, extended=fr.extended,
                               error="no message with this identifier"))
            continue
        try:
            raw = msg.decode(fr.data, decode_choices=False, scaling=False)
            phys = msg.decode(fr.data, decode_choices=False, scaling=True)
            named = msg.decode(fr.data, decode_choices=True, scaling=True)
        except Exception as e:
            cbi.emit(cbi.event("decode-error", id=fr.id, extended=fr.extended, error=str(e)))
            continue
        signals = {}
        for name, value in raw.items():
            sig = msg.get_signal_by_name(name)
            entry = {"raw": raw_text(sig, value), "physical": number(phys[name])}
            label = named[name]
            if not isinstance(label, (int, float)):
                entry["label"] = str(label)
            signals[name] = entry
        cbi.emit(cbi.event("decoded", id=fr.id, extended=fr.extended, message=msg.name, signals=signals))


def op_encode(args, caps):
    db = load(args.db)
    for doc in cbi.read_json_lines(args.messages):
        name = doc.get("message")
        values = doc.get("signals", {})
        try:
            msg = db.get_message_by_name(name)
        except KeyError:
            cbi.emit(cbi.event("encode-error", message=name, error="no such message"))
            continue
        if args.raw:
            values = {k: int(v) for k, v in values.items()}
        try:
            data = msg.encode(values, scaling=not args.raw, padding=False, strict=True)
        except Exception as e:
            cbi.emit(cbi.event("encode-error", message=name, error=str(e)))
            continue
        cbi.emit(cbi.event("encoded", message=name, id=msg.frame_id,
                           extended=bool(msg.is_extended_frame), data=bytes(data).hex()))


if __name__ == "__main__":
    cbi.run(ADAPTER, CAPABILITIES, VERSION, {
        "decode": op_decode,
        "encode": op_encode,
    })
