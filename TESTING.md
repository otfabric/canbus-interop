# Testing

| Check | Command | Needs |
|-------|---------|-------|
| Versions agree with the build inputs, fixtures are valid | `make validate` | Python 3 (jsonschema, else a container) |
| Shellcheck, Python byte-compile | `make lint` | shellcheck or Docker |
| Build the images (host architecture) | `make images` | Docker |
| Contract smoke test (capabilities, version, fixtures, exit 2 on unsupported operations and usage errors) | `make smoke` | Docker |
| Create vcan0/vcan1 | `make vcan` | Linux with CAN modules, root |
| Self-test, all suites | `make selftest` | the above |
| One suite | `make selftest-raw`, `selftest-isotp`, `selftest-dbc`, `selftest-logs` | `dbc` and `logs` need no CAN |
| ISO-TP suite in a microVM with the stock Ubuntu kernel | `scripts/microvm-isotp.sh` | Linux with KVM, QEMU, virtme-ng, Docker (to export the images) |
| Validate every document kept by smoke and self-test | `make documents` | Python 3 |
| Everything | `make ci` | Linux with CAN modules |

The self-test writes `reports/selftest.json`, `reports/selftest.md` and
`reports/documents/` (every JSON document each image printed, validated by
`make documents`). `scripts/compat-report.py reports/selftest.json` renders
[docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

Results are `pass`, `fail`, `skip` (a stack lacks the capability; never a
pass) and `known` (a difference between DBC oracles listed in
[tests/known-differences.tsv](tests/known-differences.tsv)). The self-test
exits 1 when anything failed.

## Environment variables of `scripts/selftest.py`

`DOCKER` (e.g. `sudo docker`), `IMAGE_TEMPLATE` (default
`ghcr.io/otfabric/canbus-interop-{adapter}:dev`), `ADAPTERS`, `SUITES`,
`VCAN`, `VCAN2`, `ADMIN` (prefix of `ip link` for the interface down/up
scenarios; `none` skips them), `REPORTS`, `WORK`.

Every socket of a network namespace shares a `vcan` interface: when other
tests use the same host (for example an implementation's own interop suite
on vcan0), give the self-test interfaces of its own:
`make vcan selftest VCAN=vcan10 VCAN2=vcan11`. Frames of another test on the
same interface show up as unexpected frames and fail scenarios.

## macOS

Docker Desktop's Linux kernel has no CAN modules: `make images smoke
selftest-dbc` works there; for the raw and ISO-TP suites use a Linux VM
(for example Lima with an Ubuntu image: `sudo modprobe vcan can-isotp`
works on its kernel) or CI.

## Without Docker: `scripts/chroot-run`

`scripts/chroot-run` stands in for the `docker run` and `docker kill` calls
of the self-test: `chroot-run export <image>...` unpacks the images' root
file systems (with their `Env` and `Entrypoint`) into `$ROOTFS`, and
`DOCKER=scripts/chroot-run` makes the self-test run each adapter with
`unshare -m` and `chroot` on the host's network namespace, `/work` bind
mounted. The programs are exactly those of the images. It needs root, and
no Docker daemon. Verified: the whole `isotp` suite, 78 pass, in the Lima VM
(arm64, Linux 7.0) and in the microVM below.

## Kernel ISO-TP in a microVM

GitHub's amd64 runners run an Azure kernel without `can-isotp`; their arm64
runners ship it. Two ways to get the kernel's ISO-TP on amd64, both kept:

| | microVM (used by CI on amd64) | Out-of-tree build (fallback; used by the Release workflow) |
|---|---|---|
| How | `scripts/microvm-isotp.sh`: virtme-ng boots Ubuntu's generic kernel (6.8 on 24.04) with KVM; the images run in the guest through `chroot-run` | `scripts/ci-can-modules.sh` compiles `net/can/isotp.c` of the runner kernel's version against its headers and loads it |
| Kernel ISO-TP tested | the distribution's own module, as users run it | upstream source of the same version, built by us |
| Result (2026-10-28) | isotp suite 78 pass, 0 fail, 0 skip | 78 pass (v0.1.0 releases) |
| Time | about 7.5 min for the suite (two vCPUs, a guest boot, and a chroot per adapter run) | about 1 min plus 1 min to build |
| Needs | `/dev/kvm` (amd64 runners only; arm64 runners have none) | kernel headers of the runner, network access to the kernel source |
| Fails when | KVM or the Ubuntu kernel packages are unavailable | the runner kernel's source is not published under the expected tag |

So `ci.yml` runs the `raw`, `dbc` and `logs` suites on the amd64 runner
(no out-of-tree build: `CAN_ISOTP_OUT_OF_TREE=0`) and the `isotp` suite in
the microVM job; arm64 runs every suite natively. The out-of-tree build
remains in `ci-can-modules.sh` as the fallback and in the Release workflow,
where every suite gates the published images and a few minutes matter
less than not depending on KVM. Docker inside the guest was not needed:
running the exported image file systems with chroot keeps the guest simple
and tests the same programs.

## CI

`.github/workflows/ci.yml` runs validate, lint, the image builds, the smoke
test and the self-test natively on `ubuntu-24.04` (amd64; suites `raw`,
`dbc`, `logs`) and `ubuntu-24.04-arm` (arm64; every suite), after loading
`vcan` and `can-isotp` (`scripts/ci-can-modules.sh`), and the `isotp` suite
in a microVM on amd64 (above). Reports are uploaded as artifacts. The weekly
Upstream workflow compares the pins with the latest upstream releases
(`scripts/latest-upstream.py`) and keeps an issue open while one is behind.
