# Releases

Each section is the body of its GitHub release (`scripts/release-notes.sh`).
A release is a pushed tag `vX.Y.Z` equal to `interop_version` in
versions.yaml: the Release workflow builds and self-tests every image
natively on amd64 and arm64, pushes `<image>:vX.Y.Z-<arch>`, joins them into
the multi-arch `<image>:vX.Y.Z` and publishes the release with the digests.

## v0.1.0

**Date:** 2026-10-27
**Previous release:** none

First release of canbus-interop.

* Container contract 1.0 ([docs/CONTAINER_CONTRACT.md](docs/CONTAINER_CONTRACT.md)) and JSON Schemas 1.0.
* Images: `canbus-interop-canutils` (can-utils v2025.01; kernel CAN_RAW and
  CAN_ISOTP), `-pythoncan` (python-can 4.6.1), `-socketcanrs` (socketcan
  4.0.0), `-scapy` (Scapy 2.8.0), `-pythoncanisotp` (python-can-isotp 2.0.7),
  `-cantools` (cantools 45.1.0), `-canmatrix` (canmatrix 1.3.3), for
  linux/amd64 and linux/arm64.
* Fixtures: frames (standard, extended, remote, every FD length, ESI, error
  frames, a 2000-frame sequence), seven DBC databases with decode and encode
  vectors, a KCD network.
* Self-test on vcan: raw CAN pairs, filters, loopback, receive-own, error
  frames, multi-consumer, capture/replay, malformed input, interface
  down/up; ISO-TP kernel ↔ python-can-isotp; cantools ↔ canmatrix.

---
