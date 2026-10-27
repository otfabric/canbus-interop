# Interoperability testing with canbus-interop

How an implementation under test (for example go-canbus) uses these images,
and what a test on virtual CAN can and cannot show.

## Set-up

1. A Linux host (or VM) with the CAN modules: `vcan`, `can-raw`,
   `can-isotp` (mainline since Linux 5.10). On Ubuntu runners install
   `linux-modules-extra-$(uname -r)`; Docker Desktop's kernel has no CAN.
2. `scripts/setup-vcan.sh vcan0 vcan1` (root): CAN FD capable `vcan`
   interfaces (MTU 72) in the host network namespace.
3. Run the images with `--network host`, pinned by digest. Start a receiving
   container and wait for its `ready` line before transmitting.

The contract, documents and exit codes are in
[docs/CONTAINER_CONTRACT.md](docs/CONTAINER_CONTRACT.md); a consumer depends
on that and on [schemas/](schemas), never on an adapter's source. Select
scenarios from `print-capabilities`; record a scenario a stack cannot do as
skipped, not as passed.

## Both directions

Test the implementation as sender with each receiving image and as receiver
with each sending image, and for ISO-TP against both the kernel (`canutils`)
and python-can-isotp, as sender and as receiver. For DBC, compare encoded
bytes and decoded raw and physical values with cantools and canmatrix, not
only whether a file parses.

## Isolation

* `vcan` (used here): every socket of the namespace shares the interface;
  run one scenario at a time per interface, or give each a separate
  interface.
* `vxcan` pairs: a tunnel between two network namespaces, each end in one
  container's namespace (`ip link add vxcan0 type vxcan peer name vxcan1
  netns <pid>`). Gives per-container isolation; not used by the self-test
  because every reference speaks to the same bus anyway.
* `can-gw` can route frames between interfaces (and namespaces) for
  multi-bus topologies.

## What virtual CAN shows, and what needs hardware

| Testable on vcan | Needs a real CAN controller and bus |
|------------------|-------------------------------------|
| Frame encoding/decoding of the socket API: identifiers, flags, DLC, FD lengths, BRS/ESI flags as bits | Bit timing, sample point, actual bit-rate switching on the wire |
| Kernel filters, error-frame masks, loopback, receive-own | Arbitration between nodes, priority inversion, bus load |
| Error frames as injected data | Error frames produced by a controller: error counters, error passive, bus-off and recovery |
| ISO-TP segmentation, flow control, STmin, timeouts, invalid sequences | ISO-TP timing on a loaded bus, transceiver delays |
| Order and loss in userspace (socket buffer) | Lost frames on the wire, ACK errors, no-ACK when alone on the bus |
| Interface down/up | Controller restart (`restart-ms`), bus termination, transceiver faults |
| Capture and replay | Hardware timestamps |

`vcan` delivers every frame instantly and never loses one on the "wire";
ESI and BRS are just flag bits there. Do not present a vcan result as
evidence of physical-layer behaviour.
