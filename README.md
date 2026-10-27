# canbus-interop

Independent CAN, ISO-TP and DBC reference implementations in containers, with
one command-line contract, for interoperability testing of CAN software such
as [go-canbus](https://github.com/otfabric/go-canbus). Nothing in this
repository depends on go-canbus.

Every image runs one upstream stack behind the same commands, flags, JSON
documents and exit codes ([container contract](docs/CONTAINER_CONTRACT.md),
[JSON Schemas](schemas)). A self-test runs the stacks against each other on
Linux virtual CAN (`vcan`), so a test suite can trust a reference before it
trusts a result against it.

## Stacks

| Adapter | Upstream | Version | Language | Licence | What it exercises | Operations |
|---------|----------|---------|----------|---------|-------------------|------------|
| `canutils` | [linux-can/can-utils](https://github.com/linux-can/can-utils) | v2025.01 | C | GPL-2.0-only OR BSD-3-Clause | Kernel `CAN_RAW` (cansend, candump, canplayer); **kernel `CAN_ISOTP`** (isotpsend, isotprecv) | send, receive, capture, replay, isotp-send, isotp-receive |
| `pythoncan` | [python-can](https://github.com/hardbyte/python-can) | 4.6.1 | Python | LGPL-3.0-only | Kernel `CAN_RAW` through Python's socket module; python-can's log readers/writers (candump, Vector ASC and BLF, PEAK TRC, CSV) | send, receive, capture, replay, log-convert |
| `socketcanrs` | [socketcan-rs](https://github.com/socketcan-rs/socketcan-rs) (crate `socketcan`) | 4.0.0 | Rust | MIT | Kernel `CAN_RAW` through libc/socket2 | send, receive |
| `scapy` | [Scapy](https://github.com/secdev/scapy) | 2.8.0 | Python | GPL-2.0-only | Kernel `CAN_RAW` (NativeCANSocket) with Scapy's own frame codec | send, receive |
| `pythoncanisotp` | [python-can-isotp](https://github.com/pylessard/python-can-isotp) | 2.0.7 | Python | MIT | **Userspace ISO-TP** state machine over python-can | isotp-send, isotp-receive |
| `cantools` | [cantools](https://github.com/cantools/cantools) | 45.1.1 | Python | MIT | DBC and AUTOSAR ARXML parser, signal codec | decode, encode |
| `canmatrix` | [canmatrix](https://github.com/ebroecker/canmatrix) | 1.3.3 | Python | BSD-2-Clause | DBC/KCD/ARXML parser and signal codec | decode, encode, convert (KCD, ARXML → DBC) |

Capabilities per image (CAN FD, BRS, ESI, remote frames, filters, ISO-TP
address modes, DBC constructs): [docs/CAPABILITIES.md](docs/CAPABILITIES.md)
and `print-capabilities`.

### What "independent" means here

* The four raw-CAN clients (can-utils, python-can, socketcan-rs, Scapy) are
  independently written **userspace** programs, but all of them use the same
  Linux SocketCAN `CAN_RAW` implementation in the kernel. They are
  independent in how they build, parse and present frames (identifier
  flags, DLC handling, FD flags, filters, socket options, log formats), not
  in CAN controller or bus behaviour. None of them is a CAN controller.
* The two ISO-TP implementations are genuinely independent: the Linux
  kernel's `CAN_ISOTP` (driven by can-utils) and python-can-isotp's pure
  userspace state machine.
* cantools and canmatrix are independent DBC parsers and codecs.

## Quick start

On Linux with the CAN modules (Ubuntu: `linux-modules-extra-$(uname -r)`):

```sh
make vcan                    # vcan0 and vcan1, CAN FD capable (sudo)
make images                  # every image for this machine's architecture
make smoke selftest          # contract smoke test, reference-to-reference self-test
```

On macOS or with Docker Desktop (no CAN in its kernel): `make images smoke
selftest-dbc` runs everything that does not need a CAN interface.

Use a published image directly:

```sh
docker run --rm --network host ghcr.io/otfabric/canbus-interop-canutils:v0.1.0 \
    receive --interface vcan0 --count 1 --fd
echo '{"id":291,"fd":true,"brs":true,"len":12,"data":"000102030405060708090a0b"}' |
    docker run --rm -i --network host ghcr.io/otfabric/canbus-interop-socketcanrs:v0.1.0 send --fd
```

CAN interfaces belong to a network namespace and ordinary Docker networks do
not carry CAN, so containers run with `--network host` against `vcan`
interfaces of the host namespace ([docs/CONTAINER_CONTRACT.md](docs/CONTAINER_CONTRACT.md#image-layout)).

## Self-test

`scripts/selftest.py` ([TESTING.md](TESTING.md)) runs, capability driven:

* **raw**: every sender against every receiver for each frame fixture
  (11-bit, 29-bit, every classical length, every CAN FD length with and
  without BRS, ESI, remote frames, a paced 2000-frame sequence checked for
  order and loss), an unpaced burst, kernel filters (exact, masked, standard
  or extended only, inverted, joined), local loopback off, receive own
  messages, four receivers at once, capture and replay across stacks,
  malformed frame documents, missing interface, interface down and up.
* **isotp**: kernel ↔ python-can-isotp in both directions: single frames,
  multi-frame up to 4095 bytes, first-frame escape (5000 bytes), block sizes,
  STmin in ms and µs, padding, extended and mixed addressing, 29-bit
  identifiers, CAN FD (SF escape, 64-byte frames), missing flow control, and
  hand-made frame sequences (wrong sequence number, consecutive frame
  without first frame, empty single frame) injected by a raw-CAN adapter.
* **dbc**: cantools and canmatrix decode and encode the [DBC
  fixtures](fixtures/dbc) and the [ARXML fixtures](fixtures/arxml) and must
  agree byte for byte and value for value; KCD and ARXML fixtures are
  converted by canmatrix and decoded by both. Accepted
  differences are listed in [tests/known-differences.tsv](tests/known-differences.tsv)
  and reported as `known`, never as `pass`.

* **logs**: python-can's ASC, BLF, TRC and CSV writers and readers: the
  committed [log fixtures](fixtures/logs) read back as committed, and the
  losses of each format match [docs/LOG_FORMATS.md](docs/LOG_FORMATS.md).

A scenario a stack cannot do is reported as `skip` with the reason. Results
of the latest run: [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

## Documentation

| Document | Content |
|----------|---------|
| [docs/CONTAINER_CONTRACT.md](docs/CONTAINER_CONTRACT.md) | Commands, flags, documents, exit codes |
| [docs/CAPABILITIES.md](docs/CAPABILITIES.md) | Capability matrix, with the evidence for each value |
| [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) | Self-test results |
| [docs/FIXTURES.md](docs/FIXTURES.md) | Frame, DBC, KCD, ARXML and log fixtures |
| [docs/LOG_FORMATS.md](docs/LOG_FORMATS.md) | What python-can keeps of each log format |
| [INTEROPERABILITY.md](INTEROPERABILITY.md) | How to test an implementation against these images; what vcan can and cannot show |
| [TESTING.md](TESTING.md) | Running the tests |
| [LIMITATIONS.md](LIMITATIONS.md) | What is not covered |
| [SECURITY.md](SECURITY.md) | Reporting, image hardening, safety of CAN traffic |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Adding an adapter, changing the contract |
| [RELEASE.md](RELEASE.md) / [CHANGELOG.md](CHANGELOG.md) | Releases |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | Upstream licences |

## Licence

The adapters, scripts, schemas and fixtures of this repository are MIT
licensed ([LICENSE](LICENSE)). Each image also contains its upstream stack
under that stack's licence ([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md));
the canutils image includes the source code of its GPL-2.0 binaries.
