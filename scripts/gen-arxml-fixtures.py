#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate the ARXML fixtures (fixtures/arxml/*.arxml) and their vectors.

AUTOSAR 4 (schema namespace r4.0) CAN system descriptions, original work of
canbus-interop. Each <name>.arxml gets <name>.frames.jsonl (decode vectors)
and <name>.messages.jsonl (encode vectors). Run from the repository root:

    python3 scripts/gen-arxml-fixtures.py
"""

import json
import os
import random

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "arxml")


def sig_mapping(name, sig, order, pos):
    return f"""            <I-SIGNAL-TO-I-PDU-MAPPING>
              <SHORT-NAME>{name}</SHORT-NAME>
              <I-SIGNAL-REF DEST="I-SIGNAL">/Signals/{sig}</I-SIGNAL-REF>
              <PACKING-BYTE-ORDER>{order}</PACKING-BYTE-ORDER>
              <START-POSITION>{pos}</START-POSITION>
              <TRANSFER-PROPERTY>PENDING</TRANSFER-PROPERTY>
            </I-SIGNAL-TO-I-PDU-MAPPING>"""


def isignal(name, length, base=None, init=None):
    nrp = ""
    if base:
        nrp = f"""
          <NETWORK-REPRESENTATION-PROPS><SW-DATA-DEF-PROPS-VARIANTS><SW-DATA-DEF-PROPS-CONDITIONAL>
            <BASE-TYPE-REF DEST="SW-BASE-TYPE">/BaseTypes/{base}</BASE-TYPE-REF>
          </SW-DATA-DEF-PROPS-CONDITIONAL></SW-DATA-DEF-PROPS-VARIANTS></NETWORK-REPRESENTATION-PROPS>"""
    iv = ""
    if init is not None:
        iv = f"""
          <INIT-VALUE><NUMERICAL-VALUE-SPECIFICATION><VALUE>{init}</VALUE></NUMERICAL-VALUE-SPECIFICATION></INIT-VALUE>"""
    return f"""        <I-SIGNAL>
          <SHORT-NAME>{name}</SHORT-NAME>{iv}
          <LENGTH>{length}</LENGTH>{nrp}
          <SYSTEM-SIGNAL-REF DEST="SYSTEM-SIGNAL">/SystemSignals/{name}</SYSTEM-SIGNAL-REF>
        </I-SIGNAL>"""


def syssig(name, cm=None, unit=None):
    props = ""
    if cm:
        u = f"\n            <UNIT-REF DEST=\"UNIT\">/Units/{unit}</UNIT-REF>" if unit else ""
        props = f"""
          <PHYSICAL-PROPS><SW-DATA-DEF-PROPS-VARIANTS><SW-DATA-DEF-PROPS-CONDITIONAL>
            <COMPU-METHOD-REF DEST="COMPU-METHOD">/CompuMethods/{cm}</COMPU-METHOD-REF>{u}
          </SW-DATA-DEF-PROPS-CONDITIONAL></SW-DATA-DEF-PROPS-VARIANTS></PHYSICAL-PROPS>"""
    return f"""        <SYSTEM-SIGNAL>
          <SHORT-NAME>{name}</SHORT-NAME>{props}
        </SYSTEM-SIGNAL>"""


def linear(name, offset, factor):
    return f"""        <COMPU-METHOD>
          <SHORT-NAME>{name}</SHORT-NAME>
          <CATEGORY>LINEAR</CATEGORY>
          <COMPU-INTERNAL-TO-PHYS><COMPU-SCALES>
            <COMPU-SCALE>
              <COMPU-RATIONAL-COEFFS>
                <COMPU-NUMERATOR><V>{offset}</V><V>{factor}</V></COMPU-NUMERATOR>
                <COMPU-DENOMINATOR><V>1</V></COMPU-DENOMINATOR>
              </COMPU-RATIONAL-COEFFS>
            </COMPU-SCALE>
          </COMPU-SCALES></COMPU-INTERNAL-TO-PHYS>
        </COMPU-METHOD>"""


def texttable(name, entries, linear_part=None):
    scales = ""
    for v, t in entries:
        scales += f"""
            <COMPU-SCALE>
              <LOWER-LIMIT INTERVAL-TYPE="CLOSED">{v}</LOWER-LIMIT>
              <UPPER-LIMIT INTERVAL-TYPE="CLOSED">{v}</UPPER-LIMIT>
              <COMPU-CONST><VT>{t}</VT></COMPU-CONST>
            </COMPU-SCALE>"""
    cat = "TEXTTABLE"
    if linear_part:
        lo, hi, off, fac = linear_part
        cat = "SCALE_LINEAR_AND_TEXTTABLE"
        scales += f"""
            <COMPU-SCALE>
              <LOWER-LIMIT INTERVAL-TYPE="CLOSED">{lo}</LOWER-LIMIT>
              <UPPER-LIMIT INTERVAL-TYPE="CLOSED">{hi}</UPPER-LIMIT>
              <COMPU-RATIONAL-COEFFS>
                <COMPU-NUMERATOR><V>{off}</V><V>{fac}</V></COMPU-NUMERATOR>
                <COMPU-DENOMINATOR><V>1</V></COMPU-DENOMINATOR>
              </COMPU-RATIONAL-COEFFS>
            </COMPU-SCALE>"""
    return f"""        <COMPU-METHOD>
          <SHORT-NAME>{name}</SHORT-NAME>
          <CATEGORY>{cat}</CATEGORY>
          <COMPU-INTERNAL-TO-PHYS><COMPU-SCALES>{scales}
          </COMPU-SCALES></COMPU-INTERNAL-TO-PHYS>
        </COMPU-METHOD>"""


def identical(name):
    return f"""        <COMPU-METHOD>
          <SHORT-NAME>{name}</SHORT-NAME>
          <CATEGORY>IDENTICAL</CATEGORY>
        </COMPU-METHOD>"""


def triggering(name, frame, ident, mode, fd=False):
    b = """
                  <CAN-FRAME-RX-BEHAVIOR>CAN-FD</CAN-FRAME-RX-BEHAVIOR>
                  <CAN-FRAME-TX-BEHAVIOR>CAN-FD</CAN-FRAME-TX-BEHAVIOR>""" if fd else ""
    return f"""                <CAN-FRAME-TRIGGERING>
                  <SHORT-NAME>{name}</SHORT-NAME>
                  <FRAME-REF DEST="CAN-FRAME">/Frames/{frame}</FRAME-REF>
                  <CAN-ADDRESSING-MODE>{mode}</CAN-ADDRESSING-MODE>{b}
                  <IDENTIFIER>{ident}</IDENTIFIER>
                </CAN-FRAME-TRIGGERING>"""


def frame(name, length, pdu, pos=0):
    return f"""        <CAN-FRAME>
          <SHORT-NAME>{name}</SHORT-NAME>
          <FRAME-LENGTH>{length}</FRAME-LENGTH>
          <PDU-TO-FRAME-MAPPINGS>
            <PDU-TO-FRAME-MAPPING>
              <SHORT-NAME>{pdu}Mapping</SHORT-NAME>
              <PACKING-BYTE-ORDER>MOST-SIGNIFICANT-BYTE-LAST</PACKING-BYTE-ORDER>
              <PDU-REF DEST="I-SIGNAL-I-PDU">/Pdus/{pdu}</PDU-REF>
              <START-POSITION>{pos}</START-POSITION>
            </PDU-TO-FRAME-MAPPING>
          </PDU-TO-FRAME-MAPPINGS>
        </CAN-FRAME>"""


def pdu(name, length, mappings):
    return f"""        <I-SIGNAL-I-PDU>
          <SHORT-NAME>{name}</SHORT-NAME>
          <LENGTH>{length}</LENGTH>
          <I-SIGNAL-TO-PDU-MAPPINGS>
{chr(10).join(mappings)}
          </I-SIGNAL-TO-PDU-MAPPINGS>
        </I-SIGNAL-I-PDU>"""


def package(name, elements):
    return f"""    <AR-PACKAGE>
      <SHORT-NAME>{name}</SHORT-NAME>
      <ELEMENTS>
{chr(10).join(elements)}
      </ELEMENTS>
    </AR-PACKAGE>"""


def document(comment, cluster, triggerings, packages):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- SPDX-License-Identifier: MIT -->
<!-- canbus-interop fixture: {comment} -->
<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://autosar.org/schema/r4.0 AUTOSAR_4-3-0.xsd">
  <AR-PACKAGES>
    <AR-PACKAGE>
      <SHORT-NAME>Cluster</SHORT-NAME>
      <ELEMENTS>
        <CAN-CLUSTER>
          <SHORT-NAME>{cluster}</SHORT-NAME>
          <CAN-CLUSTER-VARIANTS><CAN-CLUSTER-CONDITIONAL>
            <BAUDRATE>500000</BAUDRATE>
            <PHYSICAL-CHANNELS><CAN-PHYSICAL-CHANNEL>
              <SHORT-NAME>Channel</SHORT-NAME>
              <FRAME-TRIGGERINGS>
{chr(10).join(triggerings)}
              </FRAME-TRIGGERINGS>
            </CAN-PHYSICAL-CHANNEL></PHYSICAL-CHANNELS>
          </CAN-CLUSTER-CONDITIONAL></CAN-CLUSTER-VARIANTS>
        </CAN-CLUSTER>
      </ELEMENTS>
    </AR-PACKAGE>
{chr(10).join(packages)}
  </AR-PACKAGES>
</AUTOSAR>
"""


BASE_TYPES = package("BaseTypes", [f"""        <SW-BASE-TYPE>
          <SHORT-NAME>sint{n}</SHORT-NAME>
          <CATEGORY>FIXED_LENGTH</CATEGORY>
          <BASE-TYPE-SIZE>{n}</BASE-TYPE-SIZE>
          <BASE-TYPE-ENCODING>2C</BASE-TYPE-ENCODING>
        </SW-BASE-TYPE>""" for n in (8, 16, 32)])
UNITS = package("Units", ["""        <UNIT>
          <SHORT-NAME>rpm</SHORT-NAME>
          <DISPLAY-NAME>rpm</DISPLAY-NAME>
        </UNIT>"""])

LE, BE = "MOST-SIGNIFICANT-BYTE-LAST", "MOST-SIGNIFICANT-BYTE-FIRST"

FIXTURES = {
    "basic": dict(
        comment="AUTOSAR 4 CAN cluster: Intel and Motorola signals, standard and extended identifiers, "
                "LINEAR, TEXTTABLE, SCALE_LINEAR_AND_TEXTTABLE and IDENTICAL compu methods, signed base types (2C), init values",
        cluster="Body",
        triggerings=[triggering("EngineTriggering", "Engine", 256, "STANDARD"),
                     triggering("BodyTriggering", "Body", 0x18FF1234, "EXTENDED")],
        frames=[frame("Engine", 8, "EnginePdu"), frame("Body", 8, "BodyPdu")],
        pdus=[pdu("EnginePdu", 8, [sig_mapping("SpeedMapping", "Speed", LE, 0), sig_mapping("TempMapping", "Temp", BE, 20),
                                   sig_mapping("GearMapping", "Gear", LE, 32), sig_mapping("TorqueMapping", "Torque", LE, 40),
                                   sig_mapping("ModeMapping", "Mode", LE, 56)]),
              pdu("BodyPdu", 8, [sig_mapping("DoorMapping", "Door", LE, 0), sig_mapping("LevelMapping", "Level", BE, 15),
                                 sig_mapping("TiltMapping", "Tilt", LE, 24), sig_mapping("CountMapping", "Count", BE, 39)])],
        signals=[isignal("Speed", 16), isignal("Temp", 12, init=40), isignal("Gear", 4), isignal("Torque", 16, base="sint16"),
                 isignal("Mode", 8), isignal("Door", 2), isignal("Level", 10, init=512), isignal("Tilt", 8, base="sint8"),
                 isignal("Count", 32)],
        system=[syssig("Speed", "SpeedCm", "rpm"), syssig("Temp", "TempCm"), syssig("Gear", "GearCm"), syssig("Torque", "TorqueCm"),
                syssig("Mode", "ModeCm"), syssig("Door", "DoorCm"), syssig("Level", "LevelCm"), syssig("Tilt", "TiltCm"),
                syssig("Count")],
        compu=[linear("SpeedCm", -40, 0.125), identical("TempCm"),
               texttable("GearCm", [(0, "Neutral"), (1, "First"), (2, "Second"), (15, "Invalid")]),
               linear("TorqueCm", 0, 0.5), texttable("ModeCm", [(254, "Error"), (255, "NotAvailable")], (0, 253, 0, 0.5)),
               texttable("DoorCm", [(0, "Closed"), (1, "Open"), (2, "Ajar")]), linear("LevelCm", -100, 0.25), linear("TiltCm", 0, 1)],
        messages=[
            {"message": "Engine", "signals": {"Speed": 1000, "Temp": 291, "Gear": 2, "Torque": -120.5, "Mode": 63}},
            {"message": "Engine", "signals": {"Speed": -40, "Temp": 4095, "Gear": 15, "Torque": 16383.5, "Mode": 0}},
            {"message": "Engine", "signals": {"Speed": 8151.875, "Temp": 0, "Gear": 0, "Torque": -16384, "Mode": 126.5}},
            {"message": "Body", "signals": {"Door": 2, "Level": 28, "Tilt": -128, "Count": 4294967295}},
            {"message": "Body", "signals": {"Door": 0, "Level": -100, "Tilt": 127, "Count": 305419896}},
        ]),
    "fd": dict(
        comment="AUTOSAR 4 CAN FD frames (CAN-FRAME-TX-BEHAVIOR CAN-FD) of 64 and 12 bytes, standard and extended",
        cluster="Chassis",
        triggerings=[triggering("FdLongTriggering", "FdLong", 0x200, "STANDARD", fd=True),
                     triggering("FdShortTriggering", "FdShort", 0x1ABC0000, "EXTENDED", fd=True)],
        frames=[frame("FdLong", 64, "FdLongPdu"), frame("FdShort", 12, "FdShortPdu")],
        pdus=[pdu("FdLongPdu", 64, [sig_mapping("FirstMapping", "First", LE, 0), sig_mapping("WordMapping", "Word", BE, 263),
                                    sig_mapping("SignedMapping", "Signed", LE, 400), sig_mapping("LastMapping", "Last", LE, 504)]),
              pdu("FdShortPdu", 12, [sig_mapping("HeadMapping", "Head", LE, 0), sig_mapping("TailMapping", "Tail", BE, 71)])],
        signals=[isignal("First", 8), isignal("Word", 32), isignal("Signed", 32, base="sint32"), isignal("Last", 8),
                 isignal("Head", 32), isignal("Tail", 16)],
        system=[syssig("First"), syssig("Word", "WordCm"), syssig("Signed"), syssig("Last"), syssig("Head"), syssig("Tail", "TailCm")],
        compu=[linear("WordCm", 0, 0.001), linear("TailCm", -1000, 0.1)],
        messages=[
            {"message": "FdLong", "signals": {"First": 1, "Word": 4294967.295, "Signed": -2147483648, "Last": 255}},
            {"message": "FdLong", "signals": {"First": 0, "Word": 0, "Signed": 2147483647, "Last": 0}},
            {"message": "FdShort", "signals": {"Head": 3735928559, "Tail": 5553.5}},
        ]),
    "pdu-offset": dict(
        comment="A PDU mapped at byte 2 of its frame (PDU-TO-FRAME-MAPPING START-POSITION 16). Neither cantools 45.1.1 nor "
                "canmatrix 1.3.3 applies the offset: see docs/FIXTURES.md; consumers cannot use them as oracles for it",
        cluster="Offset",
        triggerings=[triggering("ShiftedTriggering", "Shifted", 0x300, "STANDARD")],
        frames=[frame("Shifted", 8, "ShiftedPdu", 16)],
        pdus=[pdu("ShiftedPdu", 4, [sig_mapping("AMapping", "A", LE, 0), sig_mapping("BMapping", "B", LE, 8)])],
        signals=[isignal("A", 8), isignal("B", 16)],
        system=[syssig("A"), syssig("B")],
        compu=[],
        messages=[{"message": "Shifted", "signals": {"A": 17, "B": 4660}}]),
}


def frame_vectors(name, fx):
    """Decode vectors: fill patterns and seeded random payloads per frame,
    then a short payload and an unknown identifier."""
    rnd = random.Random(name)
    lines = ["# %s.arxml: patterns per message; then too short and an unknown identifier" % name]
    ids = []
    for t in fx["triggerings"]:
        ident = int(t.split("<IDENTIFIER>")[1].split("<")[0])
        ext = "EXTENDED" in t
        fd = "CAN-FD" in t
        fname = t.split("/Frames/")[1].split("<")[0]
        length = next(int(f.split("<FRAME-LENGTH>")[1].split("<")[0]) for f in fx["frames"] if "<SHORT-NAME>%s<" % fname in f)
        ids.append((ident, ext, fd, length))
        for pat in (0x00, 0xFF, 0x55, 0xAA):
            lines.append(json.dumps({"id": ident, "extended": ext, "fd": fd, "len": length, "data": bytes([pat] * length).hex()}))
        for _ in range(4):
            lines.append(json.dumps({"id": ident, "extended": ext, "fd": fd, "len": length,
                                     "data": bytes(rnd.randrange(256) for _ in range(length)).hex()}))
    ident, ext, fd, length = ids[0]
    lines.append(json.dumps({"id": ident, "extended": ext, "fd": False, "len": 4, "data": "00010203"}))
    lines.append(json.dumps({"id": 0x7FE, "extended": False, "fd": False, "len": 8, "data": "0000000000000000"}))
    return "\n".join(lines) + "\n"


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, fx in FIXTURES.items():
        xml = document(fx["comment"], fx["cluster"], fx["triggerings"], [
            package("Frames", fx["frames"]), package("Pdus", fx["pdus"]), package("Signals", fx["signals"]),
            package("SystemSignals", fx["system"]), package("CompuMethods", fx["compu"] or [identical("Unused")]),
            BASE_TYPES, UNITS])
        with open(os.path.join(OUT, name + ".arxml"), "w") as f:
            f.write(xml)
        with open(os.path.join(OUT, name + ".frames.jsonl"), "w") as f:
            f.write(frame_vectors(name, fx))
        with open(os.path.join(OUT, name + ".messages.jsonl"), "w") as f:
            f.write("# %s.arxml: physical values\n" % name)
            for m in fx["messages"]:
                f.write(json.dumps(m) + "\n")


if __name__ == "__main__":
    main()
