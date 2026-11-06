# canbus-interop-otfabric

[go-canbus](https://github.com/otfabric/go-canbus), OT Fabric's own CAN, ISO-TP
and DBC stack, behind the [container contract](../../docs/CONTAINER_CONTRACT.md),
so that other stacks can test against it. Anything that uses a
`canbus-interop-<adapter>` image can use this one in its place. Unlike those, it
is not a reference: its tags are go-canbus versions, and no harness release
contains it.

**For testing only.** Old images stay available, so check
[go-canbus advisories](https://github.com/otfabric/go-canbus/security/advisories)
for the version you pull.

**Not an independent implementation.** The image's version document declares
`independentEngine: false`, and `results.json` records `independent: false`. A
result against it says nothing independent about go-canbus when OT Fabric
produces it. A result you publish, naming the implementation and version, is
independent evidence, and we would like to hear about it.

## Use

Like every image of this repository it runs in the host network namespace,
where the `vcan` interfaces are:

```sh
docker run --rm --network host ghcr.io/otfabric/canbus-interop-otfabric:<tag> \
    receive --interface vcan0 --fd --count 10 --timeout-ms 10000
```

`<tag>` is a go-canbus version such as `v0.8.0`, or `latest`, the newest one
published. A rebuild of a version replaces its tag, so pin the digest if you need
an exact build. The digest is in the summary of the
[workflow run](https://github.com/otfabric/canbus-interop/actions/workflows/own-go-canbus.yml),
and `docker run --rm <image> print-version` prints the versions.

| | |
|---|---|
| Upstream | go-canbus, the latest release when the image was built |
| Licence | MIT; every module's licence is in the image under `/licenses` |
| Adapter name | `otfabric` |
| Language | Go |
| Raw CAN | go-canbus `socketcan` (Linux `CAN_RAW`): CAN, CAN FD, CAN XL, filters, error frames, receive-own, loopback off, candump logs |
| ISO-TP | go-canbus's userspace `isotp.Conn` on a `canbus.Bus` (not the kernel's `CAN_ISOTP`) |
| Databases | go-canbus `dbc`, `kcd` and `arxml` parsers, the `candb` codec |

## Why it is apart from the other adapters

`REQUIREMENTS.md` R1: nothing under `adapters/`, `scripts/`, `tests/` or the
top-level `Makefile` knows a library under test, and CI enforces that. This
directory and `.github/workflows/own-go-canbus.yml` are the one exception. The
scripts take the image through `ADAPTER_IMAGE_otfabric`.

No release loop can form (`otfabric/engineering` ADR-0012). This image is built
by hand, from the latest go-canbus release, and nothing is committed: this
repository has no pin of go-canbus to bump. No release or required check of
go-canbus needs the image, and go-canbus commits no pin of it. It is not in a
harness release.

## Publishing

Run the **Own stack (go-canbus)** workflow by hand, from `main`. It finds the
latest go-canbus release and the latest harness release, and prints them. It
builds the image, loads the CAN modules and creates the `vcan` interfaces of
the runner as CI does, runs the smoke test and the cross-stack self-test
(suites `raw`, `isotp`, `dbc`, `xl`) against every reference on both
architectures, then publishes `:<go-canbus version>` and `:latest`. Run from a
branch, it stops before publishing. Nothing runs it automatically, so after a
go-canbus release the image stays on the old version until someone does.

On Linux with the CAN modules (or a VM with them, see `TESTING.md`), from the
repository root:

```sh
make vcan
make -f own/go-canbus/Makefile image smoke interop
```

## What it cannot do

Declared `false` or not offered:

- `errorFramesTx`: `socketcan.Conn.Send` refuses error frames.
- `convert`, `log-convert` (`logAsc`, `logBlf`, `logTrc`, `logCsv`) and `slcan`:
  go-canbus has these (`dbc.Write`/`kcd.Write`, `capture`, `slcan`), but the
  self-test verifies them only against python-can and canmatrix, so the image
  does not offer them yet (CONTRIBUTING.md: declare only what a scenario
  verifies).
- `replay` of CAN XL logs: unsupported, as in the contract.
