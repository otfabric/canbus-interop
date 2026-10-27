# Testing

| Check | Command | Needs |
|-------|---------|-------|
| Versions agree with the build inputs, fixtures are valid | `make validate` | Python 3 (jsonschema, else a container) |
| Shellcheck, Python byte-compile | `make lint` | shellcheck or Docker |
| Build the images (host architecture) | `make images` | Docker |
| Contract smoke test (capabilities, version, fixtures, exit 2 on unsupported operations and usage errors) | `make smoke` | Docker |
| Create vcan0/vcan1 | `make vcan` | Linux with CAN modules, root |
| Self-test, all suites | `make selftest` | the above |
| One suite | `make selftest-raw`, `selftest-isotp`, `selftest-dbc` | `dbc` needs no CAN |
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

## macOS

Docker Desktop's Linux kernel has no CAN modules: `make images smoke
selftest-dbc` works there; for the raw and ISO-TP suites use a Linux VM
(for example Lima with an Ubuntu image: `sudo modprobe vcan can-isotp`
works on its kernel) or CI.

## CI

`.github/workflows/ci.yml` runs validate, lint, the image builds, the smoke
test and the whole self-test natively on `ubuntu-24.04` (amd64) and
`ubuntu-24.04-arm` (arm64), after installing
`linux-modules-extra-$(uname -r)` and loading `vcan` and `can-isotp`.
Reports are uploaded as artifacts.
