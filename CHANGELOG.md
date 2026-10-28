# Changelog

Release notes with details: [RELEASE.md](RELEASE.md).

## v0.3.0

Contract 1.2: slcan interfaces for pythoncan (`send`/`receive` with
`--interface slcan:<pyserial URL>`, python-can's slcan interface over
pyserial 3.5), capability `slcan`, self-test suite `slcan`.

## v0.2.0

Contract 1.1: `log-convert` (python-can's ASC, BLF, TRC, CSV and candump
readers and writers) and AUTOSAR ARXML for cantools and canmatrix, with
log and ARXML fixtures; cantools 45.1.1; weekly upstream pin check;
self-test suites for ARXML and logs; ISO-TP self-test runnable without
Docker (chroot) and in a microVM.

## v0.1.0

First release: container contract 1.0, JSON Schemas, seven reference images
(can-utils incl. kernel ISO-TP, python-can, socketcan-rs, Scapy,
python-can-isotp, cantools, canmatrix), frame/DBC/KCD fixtures,
capability-driven self-test (raw CAN, ISO-TP, DBC), CI on amd64 and arm64
with vcan, tag-driven multi-arch release to GHCR.
